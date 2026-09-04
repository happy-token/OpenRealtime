import {
  DEFAULT_DEVICE_CAPTURE_PROFILE,
  type CaptureMode,
  type DeviceCaptureConstraints,
  type DeviceCaptureEffectOwners,
  type DeviceCaptureProfile,
  type InputAudioAck,
  type InputAudioFrame,
  type InputEpochStarted,
} from "../protocol/v2";

export type DeviceAudioInputState =
  | "inactive"
  | "buffering"
  | "replaying"
  | "live"
  | "reset";

interface PendingFrame {
  pcm16: Int16Array;
  sequence: number;
  startSample: number;
  captureMode: CaptureMode;
}

interface SentFrame {
  sequence: number;
  nextStartSample: number;
}

export interface DeviceAudioInputRuntimeOptions {
  profile?: DeviceCaptureProfile;
  maxBufferFrames?: number;
  now?: () => number;
}

export interface DeviceAudioInputEpochOptions {
  timelineOriginMs?: number;
  requestedConstraints?: DeviceCaptureConstraints;
  effectiveConstraints?: DeviceCaptureConstraints;
  effectOwners?: DeviceCaptureEffectOwners;
}

const UNKNOWN_CAPTURE_CONSTRAINTS: DeviceCaptureConstraints = {
  echo_cancellation: null,
  noise_suppression: null,
  auto_gain_control: null,
};

const NO_CAPTURE_EFFECT_OWNERS: DeviceCaptureEffectOwners = {
  echo_cancellation: "none",
  noise_suppression: "none",
  auto_gain_control: "none",
};

export interface InputCaptureFailureEvidence {
  inputEpoch: string;
  bufferedFrames: number;
}

export class DeviceAudioInputRuntime {
  private readonly profile: DeviceCaptureProfile;
  private readonly maxBufferFrames: number;
  private readonly now: () => number;
  private pending: PendingFrame[] = [];
  private inFlight = new Map<number, SentFrame>();
  private inputEpoch: string | null = null;
  private nextSequence = 0;
  private nextStartSample = 0;
  private released = false;
  private releaseAtMs: number | null = null;
  private replayStartedAtMs: number | null = null;
  private replayFramesSent = 0;
  private highestAcknowledgedSequence = -1;
  private acknowledgedStartSample = 0;
  private downstreamBackpressured = false;
  private failureEvidence: InputCaptureFailureEvidence | null = null;
  private currentState: DeviceAudioInputState = "inactive";

  constructor(options: DeviceAudioInputRuntimeOptions = {}) {
    this.profile = options.profile ?? DEFAULT_DEVICE_CAPTURE_PROFILE;
    this.maxBufferFrames = options.maxBufferFrames
      ?? Math.ceil(this.profile.max_buffer_ms / this.profile.frame_duration_ms);
    this.now = options.now ?? (() => performance.now());
    if (this.maxBufferFrames < 1) throw new Error("maxBufferFrames must be positive");
    if (this.profile.queue_low_watermark >= this.profile.queue_high_watermark) {
      throw new Error("queue low watermark must be lower than high watermark");
    }
  }

  get state(): DeviceAudioInputState {
    return this.currentState;
  }

  get backpressured(): boolean {
    return this.downstreamBackpressured;
  }

  get activeInputEpoch(): string | null {
    return this.inputEpoch;
  }

  get bufferedFrameCount(): number {
    return this.pending.length;
  }

  get lastFailure(): InputCaptureFailureEvidence | null {
    return this.failureEvidence;
  }

  beginEpoch(
    inputEpoch: string,
    options: DeviceAudioInputEpochOptions = {},
  ): InputEpochStarted {
    if (!inputEpoch) throw new Error("input epoch must be non-empty");
    this.clear();
    this.inputEpoch = inputEpoch;
    this.currentState = "buffering";
    return {
      type: "input_epoch_started",
      input_epoch: inputEpoch,
      format: {
        format_id: "pcm16-16k-mono",
        encoding: "pcm_s16le",
        sample_rate_hz: 16_000,
        channels: 1,
      },
      requested_profile: this.profile,
      effective_profile: this.profile,
      timeline_origin_ms: options.timelineOriginMs ?? this.now(),
      requested_constraints: options.requestedConstraints ?? UNKNOWN_CAPTURE_CONSTRAINTS,
      effective_constraints: options.effectiveConstraints ?? UNKNOWN_CAPTURE_CONSTRAINTS,
      effect_owners: options.effectOwners ?? NO_CAPTURE_EFFECT_OWNERS,
    };
  }

  pushFrame(pcm16: Int16Array, captureMode?: CaptureMode): void {
    if (this.inputEpoch === null || this.currentState === "reset") {
      throw new Error("input epoch is not active");
    }
    if (pcm16.length === 0) return;
    if (this.pending.length + this.inFlight.size >= this.maxBufferFrames) {
      const inputEpoch = this.inputEpoch;
      const bufferedFrames = this.pending.length + this.inFlight.size;
      this.reset();
      this.failureEvidence = { inputEpoch, bufferedFrames };
      throw new Error("input epoch overflow");
    }
    this.pending.push({
      pcm16: pcm16.slice(),
      sequence: this.nextSequence,
      startSample: this.nextStartSample,
      captureMode: captureMode ?? (this.released ? "live" : "prebuffer"),
    });
    this.nextSequence += 1;
    this.nextStartSample += pcm16.length;
    if (this.released && captureMode === "prebuffer" && this.currentState === "live") {
      this.currentState = "replaying";
      this.replayStartedAtMs = this.now();
      this.replayFramesSent = 0;
    }
  }

  release(inputEpoch: string, nowMs = this.now()): void {
    if (inputEpoch !== this.inputEpoch || this.currentState !== "buffering") {
      throw new Error("release does not match the buffering input epoch");
    }
    this.released = true;
    this.releaseAtMs = nowMs;
    this.currentState = this.pending.length === 0 ? "live" : "replaying";
    this.replayStartedAtMs = this.pending.length === 0 ? null : nowMs;
    this.replayFramesSent = 0;
  }

  drain(maxFrames: number, nowMs = this.now()): InputAudioFrame[] {
    if (!this.released || maxFrames <= 0 || this.inputEpoch === null) return [];
    this.assertCatchupDeadline(nowMs);
    if (this.downstreamBackpressured) return [];

    const watermarkCapacity = this.profile.queue_high_watermark - this.inFlight.size;
    let count = Math.min(maxFrames, this.pending.length, watermarkCapacity);
    if (this.currentState === "replaying") {
      const replayStartedAtMs = this.replayStartedAtMs ?? this.releaseAtMs ?? nowMs;
      const allowed = 1 + Math.floor(
        Math.max(0, nowMs - replayStartedAtMs)
          * this.profile.max_replay_rate
          / this.profile.frame_duration_ms,
      );
      count = Math.min(count, Math.max(0, allowed - this.replayFramesSent));
    }

    const drained = this.pending.splice(0, count).map((frame) => {
      const output = {
        type: "input_audio_frame" as const,
        input_epoch: this.inputEpoch as string,
        sequence: frame.sequence,
        start_sample: frame.startSample,
        sample_count: frame.pcm16.length,
        capture_mode: frame.captureMode,
        pcm16_base64: encodePcm16(frame.pcm16),
      };
      frame.pcm16.fill(0);
      this.inFlight.set(frame.sequence, {
        sequence: frame.sequence,
        nextStartSample: frame.startSample + frame.pcm16.length,
      });
      return output;
    });
    if (this.currentState === "replaying") this.replayFramesSent += drained.length;
    if (this.inFlight.size >= this.profile.queue_high_watermark) {
      this.downstreamBackpressured = true;
    }
    if (this.pending.length === 0) this.currentState = "live";
    return drained;
  }

  acknowledge(ack: InputAudioAck): boolean {
    if (ack.input_epoch !== this.inputEpoch) return false;
    if (ack.highest_contiguous_sequence < this.highestAcknowledgedSequence) return true;
    if (ack.highest_contiguous_sequence === this.highestAcknowledgedSequence) {
      if (ack.next_start_sample !== this.acknowledgedStartSample) {
        throw new Error("ACK sample position does not match sent input audio");
      }
      return true;
    }
    const target = this.inFlight.get(ack.highest_contiguous_sequence);
    if (!target) throw new Error("ACK exceeds sent input audio");
    if (target.nextStartSample !== ack.next_start_sample) {
      throw new Error("ACK sample position does not match sent input audio");
    }
    for (const sequence of this.inFlight.keys()) {
      if (sequence <= ack.highest_contiguous_sequence) this.inFlight.delete(sequence);
    }
    this.highestAcknowledgedSequence = ack.highest_contiguous_sequence;
    this.acknowledgedStartSample = ack.next_start_sample;
    if (
      this.downstreamBackpressured
      && this.inFlight.size <= this.profile.queue_low_watermark
    ) {
      this.downstreamBackpressured = false;
    }
    return true;
  }

  reset(): void {
    this.clear();
    this.inputEpoch = null;
    this.currentState = "reset";
  }

  private clear(): void {
    for (const frame of this.pending) frame.pcm16.fill(0);
    this.pending = [];
    this.inFlight.clear();
    this.nextSequence = 0;
    this.nextStartSample = 0;
    this.released = false;
    this.releaseAtMs = null;
    this.replayStartedAtMs = null;
    this.replayFramesSent = 0;
    this.highestAcknowledgedSequence = -1;
    this.acknowledgedStartSample = 0;
    this.downstreamBackpressured = false;
    this.failureEvidence = null;
  }

  private assertCatchupDeadline(nowMs: number): void {
    if (
      this.currentState !== "replaying"
      || this.releaseAtMs === null
      || nowMs - this.releaseAtMs <= this.profile.catchup_deadline_ms
    ) {
      return;
    }
    const inputEpoch = this.inputEpoch;
    const bufferedFrames = this.pending.length;
    this.reset();
    if (inputEpoch) this.failureEvidence = { inputEpoch, bufferedFrames };
    throw new Error("input catch-up deadline exceeded");
  }
}

function encodePcm16(pcm16: Int16Array): string {
  const bytes = new Uint8Array(pcm16.buffer, pcm16.byteOffset, pcm16.byteLength);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

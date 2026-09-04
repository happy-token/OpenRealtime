import { LOCAL_MIC_CHUNK_SAMPLES, readAnalyserLevel } from "@/lib/audio";
import type { ClientVoiceSessionController } from "../session/controller";
import {
  DEFAULT_DEVICE_CAPTURE_PROFILE,
  type CaptureMode,
  type InputAudioAck,
  type InputAudioFrame,
  type InputCaptureDiagnostic,
  type InputEpochStarted,
} from "../protocol/v2";
import { DeviceAudioInputRuntime } from "./input-runtime";

const LEVEL_FFT_SIZE = 256;
type InputWireFrame = InputEpochStarted | InputAudioFrame | InputCaptureDiagnostic;

interface WorkletAudioMessage {
  type: "audio_frame" | "overflow";
  inputEpoch: string;
  captureMode?: CaptureMode;
  pcm16?: ArrayBuffer;
  bufferedFrames?: number;
  aggregateEnergy?: number;
}

export interface BrowserAudioInputOptions {
  runtime: DeviceAudioInputRuntime;
  controller: ClientVoiceSessionController;
  isTransportOpen: () => boolean;
  send: (frame: InputWireFrame) => boolean;
  getNoiseSuppression: () => boolean;
  shouldDropFrame: () => boolean;
  onFailure: (message: string) => void;
  onCaptureStopped: () => void;
  getUserMedia?: (constraints: MediaStreamConstraints) => Promise<MediaStream>;
  createContext?: () => AudioContext;
  createWorklet?: (
    context: AudioContext,
    inputEpoch: string,
    processorOptions: Record<string, unknown>,
  ) => AudioWorkletNode;
  createInputEpoch?: () => string;
}

/** Owns device capture, the AudioWorklet graph, v2 epochs and input backpressure. */
export class BrowserAudioInput {
  private readonly runtime: DeviceAudioInputRuntime;
  private readonly controller: ClientVoiceSessionController;
  private readonly isTransportOpen: () => boolean;
  private readonly send: (frame: InputWireFrame) => boolean;
  private readonly getNoiseSuppression: () => boolean;
  private readonly shouldDropFrame: () => boolean;
  private readonly onFailure: (message: string) => void;
  private readonly onCaptureStopped: () => void;
  private readonly getUserMedia: (constraints: MediaStreamConstraints) => Promise<MediaStream>;
  private readonly createContext: () => AudioContext;
  private readonly createWorklet: BrowserAudioInputOptions["createWorklet"];
  private readonly createInputEpoch: () => string;
  private context: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private worklet: AudioWorkletNode | null = null;
  private analyser: AnalyserNode | null = null;
  private levelBuffer: Uint8Array<ArrayBuffer> | null = null;
  private downstreamPaused = false;
  private active = false;

  constructor(options: BrowserAudioInputOptions) {
    this.runtime = options.runtime;
    this.controller = options.controller;
    this.isTransportOpen = options.isTransportOpen;
    this.send = options.send;
    this.getNoiseSuppression = options.getNoiseSuppression;
    this.shouldDropFrame = options.shouldDropFrame;
    this.onFailure = options.onFailure;
    this.onCaptureStopped = options.onCaptureStopped;
    this.getUserMedia = options.getUserMedia
      ?? ((constraints) => navigator.mediaDevices.getUserMedia(constraints));
    this.createContext = options.createContext ?? (() => new AudioContext());
    this.createWorklet = options.createWorklet
      ?? ((context, inputEpoch, processorOptions) => new AudioWorkletNode(
        context,
        "voice-input",
        { processorOptions: { ...processorOptions, inputEpoch } },
      ));
    this.createInputEpoch = options.createInputEpoch ?? (() => crypto.randomUUID());
  }

  get isActive(): boolean {
    return this.active;
  }

  async start(): Promise<void> {
    if (this.active) return;
    const stream = await this.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: this.getNoiseSuppression(),
        autoGainControl: true,
      },
    });
    const context = this.createContext();
    try {
      await context.audioWorklet.addModule("/voice-input-worklet.js");
      if (!this.isTransportOpen()) throw new Error("语音连接尚未就绪");
      this.stream = stream;
      this.context = context;
      this.active = true;

      const source = context.createMediaStreamSource(stream);
      const analyser = context.createAnalyser();
      analyser.fftSize = LEVEL_FFT_SIZE;
      this.analyser = analyser;
      this.levelBuffer = new Uint8Array(analyser.fftSize);
      source.connect(analyser);

      const inputEpoch = this.createInputEpoch();
      const started = this.controller.beginInput(inputEpoch, this.captureEpochOptions());
      const worklet = this.createWorklet?.(
        context,
        inputEpoch,
        this.processorOptions(),
      ) as AudioWorkletNode;
      this.worklet = worklet;
      context.onstatechange = () => {
        if (
          this.context === context
          && this.active
          && context.state !== "running"
        ) {
          this.failActive("麦克风音频上下文已中断，请重新开启麦克风");
        }
      };
      worklet.onprocessorerror = () => {
        if (this.worklet === worklet && this.active) {
          this.failActive("麦克风音频处理器已停止，请重新开启麦克风");
        }
      };
      for (const track of audioTracks(stream)) {
        track.addEventListener?.("ended", () => {
          if (this.stream === stream && this.active) {
            this.failActive("麦克风设备已断开，请重新选择设备");
          }
        }, { once: true });
      }
      worklet.port.onmessage = (event: MessageEvent<WorkletAudioMessage>) => {
        this.handleWorkletMessage(event.data);
      };
      source.connect(worklet);
      this.send(started);
    } catch (error) {
      for (const track of stream.getTracks()) track.stop();
      context.onstatechange = null;
      void context.close();
      this.active = false;
      this.stream = null;
      this.context = null;
      throw error;
    }
  }

  beginEpoch(): string | null {
    if (!this.worklet || !this.active || !this.isTransportOpen()) return null;
    const inputEpoch = this.createInputEpoch();
    const started = this.controller.beginInput(inputEpoch, this.captureEpochOptions());
    this.worklet.port.postMessage({ type: "begin_epoch", input_epoch: inputEpoch });
    this.downstreamPaused = false;
    this.send(started);
    return inputEpoch;
  }

  acknowledge(ack: InputAudioAck): boolean {
    const accepted = this.runtime.acknowledge(ack);
    if (!accepted) return false;
    this.syncBackpressure();
    this.pump();
    return true;
  }

  release(inputEpoch: string): void {
    if (
      this.runtime.activeInputEpoch === inputEpoch
      && this.runtime.state === "buffering"
    ) {
      this.runtime.release(inputEpoch);
    }
    if (
      this.runtime.activeInputEpoch === inputEpoch
      && (this.runtime.state === "replaying" || this.runtime.state === "live")
    ) {
      this.worklet?.port.postMessage({ type: "release", input_epoch: inputEpoch });
      this.pump();
    }
  }

  failGap(inputEpoch: string): void {
    this.failEpoch("音频连续性中断，请重新说一次", {
      input_epoch: inputEpoch,
      outcome: "audio_gap",
      buffered_frames: this.runtime.bufferedFrameCount,
      buffered_duration_ms: (
        this.runtime.bufferedFrameCount * DEFAULT_DEVICE_CAPTURE_PROFILE.frame_duration_ms
      ),
      aggregate_energy: 0,
    });
  }

  resetForDisconnect(): void {
    this.runtime.reset();
    this.downstreamPaused = false;
    this.worklet?.port.postMessage({ type: "reset", input_epoch: "" });
  }

  failActiveCapture(message: string): void {
    this.failActive(message);
  }

  readLevel(): number {
    if (!this.analyser || !this.levelBuffer) return 0;
    return readAnalyserLevel(this.analyser, this.levelBuffer);
  }

  stop(): void {
    this.active = false;
    const stream = this.stream;
    this.stream = null;
    if (stream) {
      for (const track of stream.getTracks()) track.stop();
    }
    const worklet = this.worklet;
    this.worklet = null;
    if (worklet) {
      worklet.port.postMessage({ type: "reset", input_epoch: "" });
      worklet.port.onmessage = null;
      worklet.onprocessorerror = null;
      worklet.disconnect();
    }
    this.downstreamPaused = false;
    const context = this.context;
    this.context = null;
    if (context) {
      context.onstatechange = null;
      void context.close();
    }
    this.analyser = null;
    this.levelBuffer = null;
    this.runtime.reset();
  }

  private captureEpochOptions() {
    const track = this.stream ? audioTracks(this.stream)[0] : undefined;
    const settings = track?.getSettings?.();
    const requested = {
      echo_cancellation: true,
      noise_suppression: this.getNoiseSuppression(),
      auto_gain_control: true,
    };
    const effective = {
      echo_cancellation: settings?.echoCancellation ?? null,
      noise_suppression: settings?.noiseSuppression ?? null,
      auto_gain_control: settings?.autoGainControl ?? null,
    };
    return {
      timelineOriginMs: performance.now(),
      requestedConstraints: requested,
      effectiveConstraints: effective,
      effectOwners: {
        echo_cancellation: effective.echo_cancellation ? "device" as const : "none" as const,
        noise_suppression: effective.noise_suppression ? "device" as const : "none" as const,
        auto_gain_control: effective.auto_gain_control ? "device" as const : "none" as const,
      },
    };
  }

  private processorOptions(): Record<string, unknown> {
    return {
      flushSampleCount: LOCAL_MIC_CHUNK_SAMPLES,
      maxBufferFrames: Math.ceil(
        DEFAULT_DEVICE_CAPTURE_PROFILE.max_buffer_ms
          / DEFAULT_DEVICE_CAPTURE_PROFILE.frame_duration_ms,
      ),
      maxReplayRate: DEFAULT_DEVICE_CAPTURE_PROFILE.max_replay_rate,
      silenceThreshold: DEFAULT_DEVICE_CAPTURE_PROFILE.silence_threshold,
      preRollFrames: Math.ceil(
        DEFAULT_DEVICE_CAPTURE_PROFILE.pre_roll_ms
          / DEFAULT_DEVICE_CAPTURE_PROFILE.frame_duration_ms,
      ),
    };
  }

  private handleWorkletMessage(message: WorkletAudioMessage): void {
    if (message.type === "overflow") {
      const bufferedFrames = message.bufferedFrames ?? 0;
      this.failEpoch("麦克风缓冲已满，请重新说一次", {
        input_epoch: message.inputEpoch,
        outcome: "overflow",
        buffered_frames: bufferedFrames,
        buffered_duration_ms: (
          bufferedFrames * DEFAULT_DEVICE_CAPTURE_PROFILE.frame_duration_ms
        ),
        aggregate_energy: clamp(message.aggregateEnergy ?? 0),
      });
      return;
    }
    if (this.shouldDropFrame()) return;
    if (!message.pcm16 || !message.captureMode || !this.isTransportOpen()) {
      this.failRuntime("麦克风音频入口不可用，请重新开启麦克风");
      return;
    }
    try {
      this.runtime.pushFrame(new Int16Array(message.pcm16), message.captureMode);
      this.pump();
    } catch {
      this.failEpoch("麦克风缓冲已满，请重新说一次", {
        input_epoch: message.inputEpoch,
        outcome: "overflow",
        buffered_frames: Math.ceil(
          DEFAULT_DEVICE_CAPTURE_PROFILE.max_buffer_ms
            / DEFAULT_DEVICE_CAPTURE_PROFILE.frame_duration_ms,
        ),
        buffered_duration_ms: DEFAULT_DEVICE_CAPTURE_PROFILE.max_buffer_ms,
        aggregate_energy: 0,
      });
    }
  }

  private pump(): void {
    if (!this.isTransportOpen()) return;
    try {
      for (const frame of this.runtime.drain(
        DEFAULT_DEVICE_CAPTURE_PROFILE.queue_high_watermark,
      )) {
        this.send(frame);
      }
      this.syncBackpressure();
    } catch (error) {
      const failure = this.runtime.lastFailure;
      const inputEpoch = failure?.inputEpoch ?? this.runtime.activeInputEpoch;
      const bufferedFrames = failure?.bufferedFrames ?? this.runtime.bufferedFrameCount;
      const deadline = error instanceof Error && error.message.includes("deadline");
      this.failEpoch(
        deadline
          ? "麦克风音频追赶超时，请重新说一次"
          : "麦克风音频发送失败，请重新说一次",
        inputEpoch
          ? {
              input_epoch: inputEpoch,
              outcome: deadline ? "catchup_deadline" : "worklet_failure",
              buffered_frames: bufferedFrames,
              buffered_duration_ms: (
                bufferedFrames * DEFAULT_DEVICE_CAPTURE_PROFILE.frame_duration_ms
              ),
              aggregate_energy: 0,
            }
          : undefined,
      );
    }
  }

  private syncBackpressure(): void {
    const inputEpoch = this.runtime.activeInputEpoch;
    if (!this.worklet || !inputEpoch) return;
    const shouldPause = this.runtime.backpressured;
    if (shouldPause === this.downstreamPaused) return;
    this.downstreamPaused = shouldPause;
    this.worklet.port.postMessage({
      type: shouldPause ? "downstream_pause" : "downstream_resume",
      input_epoch: inputEpoch,
    });
  }

  private failRuntime(message: string): void {
    const inputEpoch = this.runtime.activeInputEpoch;
    const bufferedFrames = this.runtime.bufferedFrameCount;
    this.failEpoch(
      message,
      inputEpoch
        ? {
            input_epoch: inputEpoch,
            outcome: "worklet_failure",
            buffered_frames: bufferedFrames,
            buffered_duration_ms: (
              bufferedFrames * DEFAULT_DEVICE_CAPTURE_PROFILE.frame_duration_ms
            ),
            aggregate_energy: 0,
          }
        : undefined,
    );
  }

  private failActive(message: string): void {
    this.failRuntime(message);
    this.stop();
    this.onCaptureStopped();
  }

  private failEpoch(
    message: string,
    diagnostic?: Omit<InputCaptureDiagnostic, "type">,
  ): void {
    if (diagnostic && this.isTransportOpen()) {
      this.send({ type: "input_capture_diagnostic", ...diagnostic });
    }
    this.runtime.reset();
    this.downstreamPaused = false;
    this.worklet?.port.postMessage({ type: "reset", input_epoch: "" });
    this.onFailure(message);
  }
}

function audioTracks(stream: MediaStream): MediaStreamTrack[] {
  return typeof stream.getAudioTracks === "function"
    ? stream.getAudioTracks()
    : stream.getTracks();
}

function clamp(value: number): number {
  return Math.max(0, Math.min(1, value));
}

import {
  base64ToInt16Array,
  createPlaybackQuality,
  observePlaybackChunk,
  readAnalyserLevel,
  type PlaybackQuality,
} from "@/lib/audio";
import type { OutputStopResult, OutputStopTarget, PlaybackProgressV2, SentencePlaybackPermit } from "../protocol/v2";
import { DeviceAudioOutputRuntime } from "./output-runtime";

const LEVEL_FFT_SIZE = 256;

export interface BrowserAudioChunk {
  pcm16Base64: string;
  sampleRateHz: number;
  generation: number;
  speechId: string;
  sequence: number;
  isFinal: boolean;
  onEnded?: () => void;
}

export interface PlaybackQualityFrame {
  type: "playback_quality";
  generation: number;
  arrival_jitter_ms: number;
  max_chunk_gap_ms: number;
  underrun_count: number;
  underrun_total_ms: number;
  chunk_count: number;
}

export interface BrowserAudioOutputOptions {
  runtime: DeviceAudioOutputRuntime;
  createContext?: () => AudioContext;
  now?: () => number;
  onProgress?: (progress: PlaybackProgressV2) => void;
  onStarted?: (generation: number) => void;
  onResumed?: (generation: number) => void;
}

/** Owns the browser's physical output graph and playback scheduling state. */
export class BrowserAudioOutput {
  private readonly runtime: DeviceAudioOutputRuntime;
  private readonly createContext: () => AudioContext;
  private readonly now: () => number;
  private readonly onProgress?: (progress: PlaybackProgressV2) => void;
  private progressTimer: ReturnType<typeof setInterval> | null = null;
  private playedSegments: { start: number; end: number }[] = [];
  private readonly onStarted?: (generation: number) => void;
  private readonly onResumed?: (generation: number) => void;
  private context: AudioContext | null = null;
  private gainNode: GainNode | null = null;
  private analyser: AnalyserNode | null = null;
  private levelBuffer: Uint8Array<ArrayBuffer> | null = null;
  private volume = 0.8;
  private generation: number | null = null;
  private speechId: string | null = null;
  private startedGeneration: number | null = null;
  private scheduledSources: AudioBufferSourceNode[] = [];
  private readonly sourceTimes = new Map<AudioBufferSourceNode, { start: number; end: number }>();
  private readonly suppressedEnds = new WeakSet<AudioBufferSourceNode>();
  private sentenceStop: { target: OutputStopTarget; timer: ReturnType<typeof setTimeout>;
    resolve: (result: OutputStopResult) => void } | null = null;
  private nextPlayTime = 0;
  private startedAt: number | null = null;
  private scheduledEnd = 0;
  private sampleRate = 24_000;
  private quality: PlaybackQuality | null = null;
  private readonly reportedQuality = new Set<number>();
  private outputUnsafe = false;

  constructor(options: BrowserAudioOutputOptions) {
    this.runtime = options.runtime;
    this.createContext = options.createContext ?? (() => new AudioContext());
    this.now = options.now ?? (() => performance.now());
    this.onProgress = options.onProgress;
    this.onStarted = options.onStarted;
    this.onResumed = options.onResumed;
  }

  get playedAudioEndUs(): number {
    return Math.round(this.playedPositionSamples() / this.sampleRate * 1_000_000);
  }

  get playbackSampleRateHz(): number { return this.sampleRate; }

  get scheduledSourceCount(): number {
    return this.scheduledSources.length;
  }

  get activeGeneration(): number | null {
    return this.generation;
  }

  get startedPlaybackGeneration(): number | null {
    return this.startedGeneration;
  }

  get remainingScheduledMs(): number {
    if (!this.context) return 0;
    return Math.max(0, this.scheduledEnd - this.context.currentTime) * 1000;
  }

  beginEpoch(outputEpoch: string): void {
    if (!outputEpoch) throw new Error("output epoch must be non-empty");
    this.reset();
    this.runtime.beginEpoch(outputEpoch);
  }

  activate(outputEpoch?: string): void {
    if (!this.runtime.isActive) this.beginEpoch(outputEpoch ?? crypto.randomUUID());
  }

  async unlock(): Promise<void> {
    const context = this.ensureContext();
    if (context.state === "suspended") await context.resume();
  }

  canPlay(chunk: Pick<BrowserAudioChunk, "speechId" | "generation">): boolean {
    return !this.outputUnsafe && this.sentenceStop === null && this.runtime.canEnqueue(chunk);
  }

  play(chunk: BrowserAudioChunk): boolean {
    if (!this.canPlay(chunk)) return false;
    const context = this.ensureContext();
    if (context.state === "suspended") void context.resume().catch(() => undefined);
    if (this.generation !== null && (chunk.generation !== this.generation || chunk.speechId !== this.speechId)) {
      // Record using the old identity and rate before enqueue binds the new
      // speech to this generation.
      this.runtime.playbackProgress(this.generation, "playing", this.playedPositionSamples());
    }
    const accepted = this.runtime.enqueue({
      speechId: chunk.speechId,
      generation: chunk.generation,
      sequence: chunk.sequence,
      sampleRateHz: chunk.sampleRateHz,
      pcm16: base64ToInt16Array(chunk.pcm16Base64),
      isFinal: chunk.isFinal,
    });
    if (!accepted) return false;
    const outputChunk = this.runtime.takeNext();
    if (!outputChunk) return false;
    const { generation } = outputChunk;
    if (generation !== this.generation || outputChunk.speechId !== this.speechId) {
      this.stopScheduledSources();
      if (this.outputUnsafe) return false;
      this.nextPlayTime = context.currentTime;
      this.startedAt = null;
      this.playedSegments = [];
      this.scheduledEnd = 0;
      this.generation = generation;
      this.speechId = outputChunk.speechId;
      this.startedGeneration = null;
      this.quality = createPlaybackQuality(generation);
      this.reportedQuality.clear();
    }
    this.sampleRate = outputChunk.sampleRateHz;

    const float32 = new Float32Array(outputChunk.pcm16.length);
    for (let index = 0; index < outputChunk.pcm16.length; index += 1) {
      float32[index] = outputChunk.pcm16[index] / 0x8000;
    }
    const buffer = context.createBuffer(
      1,
      Math.max(float32.length, 1),
      outputChunk.sampleRateHz,
    );
    buffer.copyToChannel(float32, 0);
    if (outputChunk.pcm16.length > 0 && this.quality) {
      this.quality = observePlaybackChunk(this.quality, {
        arrivedAtMs: this.now(),
        chunkDurationMs: buffer.duration * 1000,
        underrunMs: Math.max(0, (context.currentTime - this.nextPlayTime) * 1000),
      });
    }

    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.gainNode as GainNode);
    const startAt = Math.max(this.nextPlayTime, context.currentTime);
    if (outputChunk.pcm16.length > 0) {
      if (this.startedGeneration !== generation) {
        this.startedGeneration = generation;
        this.startedAt = startAt;
        this.onStarted?.(generation);
      } else if (this.scheduledSources.length === 0) {
        this.onResumed?.(generation);
      }
    }
    this.nextPlayTime = startAt + buffer.duration;
    this.scheduledEnd = this.nextPlayTime;
    this.scheduledSources.push(source);
    this.sourceTimes.set(source, { start: startAt, end: startAt + buffer.duration });
    source.addEventListener("ended", () => {
      const naturallyEnded = this.scheduledSources.includes(source) && !this.suppressedEnds.has(source);
      this.scheduledSources = this.scheduledSources.filter((item) => item !== source);
      this.sourceTimes.delete(source);
      if (naturallyEnded) chunk.onEnded?.();
      if (this.sentenceStop && this.scheduledSources.length === 0) this.stopOutput(this.sentenceStop.target);
    });
    this.playedSegments.push({ start: startAt, end: startAt + buffer.duration });
    source.start(startAt);
    if (this.onProgress && this.progressTimer === null) {
      this.progressTimer = setInterval(() => {
        if (this.generation === null || this.startedGeneration !== this.generation) return;
        const progress = this.playbackProgress(this.generation, "playing");
        if (progress) this.onProgress?.(progress);
      }, 100);
    }
    return true;
  }

  playbackProgress(
    generation: number,
    phase: PlaybackProgressV2["phase"],
  ): PlaybackProgressV2 | null {
    return this.runtime.playbackProgress(
      generation,
      phase,
      generation === this.generation ? this.playedPositionSamples() : 0,
    );
  }

  finishGeneration(generation: number): PlaybackProgressV2 | null {
    if (generation !== this.generation || this.scheduledSources.length > 0) return null;
    const progress = this.playbackProgress(generation, "finished");
    if (this.startedGeneration === generation) this.startedGeneration = null;
    this.startedAt = null;
    this.scheduledEnd = 0;
    return progress;
  }

  cancelGeneration(generation: number): PlaybackProgressV2 | null {
    const progress = this.runtime.cancelGeneration(generation,
      generation === this.generation ? this.playedPositionSamples() : 0);
    if (generation !== this.generation) return progress;
    if (this.sentenceStop) this.stopOutput(this.sentenceStop.target);
    this.stopScheduledSources();
    this.nextPlayTime = 0;
    this.generation = null;
    this.speechId = null;
    this.playedSegments = [];
    if (this.startedGeneration === generation) this.startedGeneration = null;
    this.startedAt = null;
    this.scheduledEnd = 0;
    return progress;
  }

  stopOutput(target: OutputStopTarget): OutputStopResult {
    const result = (outcome: OutputStopResult["outcome"], position: number | null): OutputStopResult => ({
      ...target, type: "output_stop_result", outcome, played_position_samples: position,
    });
    if (target.output_epoch !== this.runtime.currentEpoch) return result("stale", null);
    const current = target.generation === this.generation && target.speech_id === this.speechId;
    const position = this.runtime.cancelSpeech(target.speech_id, target.generation,
      current ? this.playedPositionSamples() : 0);
    if (position === null) return result("stale", null);
    if (current) {
      this.stopScheduledSources();
      this.generation = null;
      this.speechId = null;
      this.startedGeneration = null;
      this.startedAt = null;
      this.playedSegments = [];
      this.scheduledEnd = 0;
      this.nextPlayTime = 0;
    }
    const receipt = this.outputUnsafe ? result("unknown", null) : result("queue_stopped", position);
    if (current && this.sentenceStop) {
      const pending = this.sentenceStop;
      this.sentenceStop = null;
      clearTimeout(pending.timer);
      pending.resolve({ ...receipt, ...pending.target });
    }
    return receipt;
  }

  stopAtSentenceEnd(target: OutputStopTarget, permit: SentencePlaybackPermit): Promise<OutputStopResult> {
    const valid = [permit.permit_id, permit.input_id, permit.response_id, permit.sentence_id]
      .every(value => typeof value === "string" && value.length > 0)
      && [permit.input_version, permit.reply_version, permit.sample_rate_hz, permit.max_wait_ms]
        .every(value => Number.isSafeInteger(value) && value > 0)
      && [permit.audio_start_samples, permit.audio_end_samples].every(value => Number.isSafeInteger(value) && value >= 0)
      && permit.audio_start_samples < permit.audio_end_samples && permit.max_wait_ms <= 5000
      && permit.sample_rate_hz <= 384000
      && (target.speech_id === permit.response_id || target.speech_id === `response:${permit.response_id}`);
    const position = this.playedPositionSamples();
    if (!valid || this.sentenceStop || target.output_epoch !== this.runtime.currentEpoch
      || target.generation !== this.generation || target.speech_id !== this.speechId
      || this.context?.state !== "running" || permit.sample_rate_hz !== this.sampleRate
      || position <= permit.audio_start_samples || position >= permit.audio_end_samples) {
      return Promise.resolve(this.stopOutput(target));
    }
    // Convert a speech-local sample boundary through actual scheduled segments;
    // network underruns are gaps in wall time, not samples in the sentence.
    let remaining = permit.audio_end_samples / this.sampleRate;
    let cutTime: number | null = null;
    for (const segment of this.playedSegments) {
      const duration = segment.end - segment.start;
      if (remaining <= duration + 1e-9) { cutTime = segment.start + remaining; break; }
      remaining -= duration;
    }
    if (cutTime === null || (cutTime - this.context.currentTime) * 1000 > permit.max_wait_ms) {
      return Promise.resolve(this.stopOutput(target));
    }
    const boundaryTime = cutTime;
    this.runtime.cancelSpeech(target.speech_id, target.generation, position);
    const promise = new Promise<OutputStopResult>(resolve => {
      const timer = setTimeout(() => this.stopOutput(target), permit.max_wait_ms);
      this.sentenceStop = { target, timer, resolve };
    });
    try {
      const retained: AudioBufferSourceNode[] = [];
      for (const source of this.scheduledSources) {
        const segment = this.sourceTimes.get(source);
        if (!segment) throw new Error("scheduled source has no sample range");
        this.suppressedEnds.add(source);
        if (segment.start >= boundaryTime - 1e-9) {
          source.stop();
          this.sourceTimes.delete(source);
        } else {
          if (segment.end > boundaryTime) source.stop(boundaryTime);
          retained.push(source);
        }
      }
      this.scheduledSources = retained;
      this.playedSegments = this.playedSegments.filter(segment => segment.start < boundaryTime)
        .map(segment => ({ start: segment.start, end: Math.min(segment.end, boundaryTime) }));
      this.scheduledEnd = boundaryTime;
      this.nextPlayTime = boundaryTime;
    } catch {
      this.outputUnsafe = true;
      if (this.gainNode) this.gainNode.gain.value = 0;
      this.stopOutput(target);
    }
    return promise;
  }

  takeQuality(generation: number): PlaybackQualityFrame | null {
    const quality = this.quality;
    if (
      !quality
      || quality.generation !== generation
      || quality.chunkCount === 0
      || this.reportedQuality.has(generation)
    ) return null;
    this.reportedQuality.add(generation);
    return {
      type: "playback_quality",
      generation,
      arrival_jitter_ms: roundTenth(quality.arrivalJitterMs),
      max_chunk_gap_ms: roundTenth(quality.maxChunkGapMs),
      underrun_count: quality.underrunCount,
      underrun_total_ms: roundTenth(quality.underrunTotalMs),
      chunk_count: quality.chunkCount,
    };
  }

  setVolume(volume: number): void {
    this.volume = volume;
    if (this.gainNode) this.gainNode.gain.value = this.outputUnsafe ? 0 : volume;
  }

  readLevel(): number {
    if (!this.analyser || !this.levelBuffer) return 0;
    return readAnalyserLevel(this.analyser, this.levelBuffer);
  }

  reset(): void {
    if (this.sentenceStop) this.stopOutput(this.sentenceStop.target);
    if (this.progressTimer !== null) clearInterval(this.progressTimer);
    this.progressTimer = null;
    this.playedSegments = [];
    this.stopScheduledSources();
    this.runtime.reset();
    this.generation = null;
    this.speechId = null;
    this.startedGeneration = null;
    this.nextPlayTime = 0;
    this.startedAt = null;
    this.scheduledEnd = 0;
    this.quality = null;
    this.reportedQuality.clear();
  }

  close(): void {
    this.reset();
    void this.context?.close();
    this.context = null;
    this.gainNode = null;
    this.analyser = null;
    this.levelBuffer = null;
  }

  private ensureContext(): AudioContext {
    if (this.context) return this.context;
    const context = this.createContext();
    const gainNode = context.createGain();
    gainNode.gain.value = this.volume;
    const analyser = context.createAnalyser();
    analyser.fftSize = LEVEL_FFT_SIZE;
    gainNode.connect(analyser);
    analyser.connect(context.destination);
    this.context = context;
    this.gainNode = gainNode;
    this.analyser = analyser;
    this.levelBuffer = new Uint8Array(analyser.fftSize);
    return context;
  }

  private playedPositionSamples(): number {
    if (!this.context || this.startedAt === null) return 0;
    const currentTime = this.context.currentTime;
    const playedSeconds = this.playedSegments.reduce(
      (sum, segment) => sum + Math.max(0, Math.min(currentTime, segment.end) - segment.start), 0,
    );
    return Math.round(playedSeconds * this.sampleRate);
  }

  private stopScheduledSources(): void {
    const sources = this.scheduledSources;
    this.scheduledSources = [];
    this.sourceTimes.clear();
    for (const source of sources) {
      try {
        source.stop();
      } catch {
        // Without a successful stop we cannot certify the output queue.
        // Keep this graph blocked; an epoch reset is not stop evidence.
        this.outputUnsafe = true;
        if (this.gainNode) this.gainNode.gain.value = 0;
      }
    }
  }
}

function roundTenth(value: number): number {
  return Math.round(value * 10) / 10;
}

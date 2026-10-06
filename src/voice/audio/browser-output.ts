import {
  base64ToInt16Array,
  createPlaybackQuality,
  observePlaybackChunk,
  readAnalyserLevel,
  type PlaybackQuality,
} from "@/lib/audio";
import type { PlaybackProgressV2 } from "../protocol/v2";
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
  private nextPlayTime = 0;
  private startedAt: number | null = null;
  private scheduledEnd = 0;
  private sampleRate = 24_000;
  private quality: PlaybackQuality | null = null;
  private readonly reportedQuality = new Set<number>();

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

  play(chunk: BrowserAudioChunk): boolean {
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
    source.addEventListener("ended", () => {
      const naturallyEnded = this.scheduledSources.includes(source);
      this.scheduledSources = this.scheduledSources.filter((item) => item !== source);
      if (naturallyEnded) chunk.onEnded?.();
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
    if (this.gainNode) this.gainNode.gain.value = volume;
  }

  readLevel(): number {
    if (!this.analyser || !this.levelBuffer) return 0;
    return readAnalyserLevel(this.analyser, this.levelBuffer);
  }

  reset(): void {
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
    for (const source of sources) {
      try {
        source.stop();
      } catch {
        // The source already reached its natural end.
      }
    }
  }
}

function roundTenth(value: number): number {
  return Math.round(value * 10) / 10;
}

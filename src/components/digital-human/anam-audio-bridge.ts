import type { AvatarAudioChunk, AvatarAudioSink } from "@/voice/audio/avatar-output";

export interface AnamAudioSession {
  interruptPersona(): void;
}

export interface AnamAgentAudioInput {
  sendAudioChunk(audio: ArrayBuffer | Uint8Array | string): void;
  endSequence(): void;
}

interface VolumeTarget {
  volume: number;
}

interface GenerationPlayback {
  bytes: number;
  firstChunkAtMs: number;
  completed: boolean;
  started: boolean;
  startTimer: ReturnType<typeof setTimeout> | null;
  endTimer: ReturnType<typeof setTimeout> | null;
  onStarted: () => void;
  onEnded: () => void;
}

const ANAM_RENDER_BUFFER_MS = 800;

/** Streams Bailian PCM directly to Anam and tracks approximate playback timing. */
export class AnamAudioBridge implements AvatarAudioSink {
  private session: AnamAudioSession | null = null;
  private input: AnamAgentAudioInput | null = null;
  private video: VolumeTarget | null = null;
  private readonly generations = new Map<number, GenerationPlayback>();
  private volume = 0.8;

  constructor(private readonly sampleRateHz = 24_000) {}

  connect(
    session: AnamAudioSession,
    input: AnamAgentAudioInput,
    video: VolumeTarget,
  ): void {
    this.session = session;
    this.input = input;
    this.video = video;
    video.volume = this.volume;
  }

  enqueue(chunk: AvatarAudioChunk): boolean {
    if (!this.session || !this.input || chunk.sampleRateHz !== this.sampleRateHz) {
      return false;
    }
    const existing = this.generations.get(chunk.generation);
    const playback = existing ?? this.createGeneration(chunk);
    try {
      if (chunk.pcm16Base64) this.input.sendAudioChunk(chunk.pcm16Base64);
    } catch {
      if (!existing) this.clearGeneration(chunk.generation);
      return false;
    }
    playback.bytes += decodedBase64ByteLength(chunk.pcm16Base64);
    playback.onEnded = chunk.onEnded;
    this.generations.set(chunk.generation, playback);
    return true;
  }

  completeGeneration(generation: number): boolean {
    const playback = this.generations.get(generation);
    if (!this.input || !playback) return false;
    if (playback.completed) return true;
    playback.completed = true;
    try {
      this.input.endSequence();
    } catch {
      this.clearGeneration(generation);
      return false;
    }
    const audioDurationMs = playback.bytes / (this.sampleRateHz * 2) * 1000;
    const expectedEndAt = playback.firstChunkAtMs + ANAM_RENDER_BUFFER_MS + audioDurationMs;
    playback.endTimer = setTimeout(() => {
      const current = this.generations.get(generation);
      if (!current) return;
      this.clearGeneration(generation);
      current.onEnded();
    }, Math.max(0, expectedEndAt - Date.now()));
    return true;
  }

  cancelGeneration(generation: number): void {
    if (!this.generations.has(generation)) return;
    this.clearGeneration(generation);
    try {
      this.session?.interruptPersona();
      this.input?.endSequence();
    } catch {
      // A disconnected renderer is already effectively interrupted.
    }
  }

  isActive(generation: number): boolean {
    return this.generations.has(generation);
  }

  reset(): void {
    for (const generation of this.generations.keys()) this.clearGeneration(generation);
  }

  disconnect(): void {
    this.reset();
    this.session = null;
    this.input = null;
    this.video = null;
  }

  setVolume(volume: number): void {
    this.volume = Math.max(0, Math.min(1, volume));
    if (this.video) this.video.volume = this.volume;
  }

  private createGeneration(chunk: AvatarAudioChunk): GenerationPlayback {
    const generation = chunk.generation;
    const playback: GenerationPlayback = {
      bytes: 0,
      firstChunkAtMs: Date.now(),
      completed: false,
      started: false,
      startTimer: null,
      endTimer: null,
      onStarted: chunk.onStarted,
      onEnded: chunk.onEnded,
    };
    playback.startTimer = setTimeout(() => {
      const current = this.generations.get(generation);
      if (!current || current.started) return;
      current.started = true;
      current.onStarted();
    }, ANAM_RENDER_BUFFER_MS);
    this.generations.set(generation, playback);
    return playback;
  }

  private clearGeneration(generation: number): void {
    const playback = this.generations.get(generation);
    if (!playback) return;
    if (playback.startTimer) clearTimeout(playback.startTimer);
    if (playback.endTimer) clearTimeout(playback.endTimer);
    this.generations.delete(generation);
  }
}

function decodedBase64ByteLength(value: string): number {
  if (!value) return 0;
  const padding = value.endsWith("==") ? 2 : value.endsWith("=") ? 1 : 0;
  return Math.max(0, Math.floor(value.length * 3 / 4) - padding);
}

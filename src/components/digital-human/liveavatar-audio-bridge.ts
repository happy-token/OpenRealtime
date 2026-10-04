import { AvatarPlaybackClock, type AvatarMediaClock } from "@/voice/audio/avatar-playback-clock";
import type { AvatarAudioChunk, AvatarAudioSink } from "@/voice/audio/avatar-output";

export interface LiveAvatarAudioSession {
  repeatAudio(audioBase64: string): string;
  interrupt(): void;
}

type VolumeTarget = AvatarMediaClock;

interface BufferedGeneration {
  clock: AvatarPlaybackClock;
  chunks: string[];
  onStarted: () => void;
  onEnded: () => void;
}

interface ActivePlayback {
  clock: AvatarPlaybackClock;
  generation: number;
  onEnded: () => void;
}

/**
 * Buffers one OpenRealtime response before handing it to LiveAvatar. The public
 * LiveAvatar SDK closes an utterance after each repeatAudio call, so forwarding
 * individual TTS deltas would break lip-sync at every network chunk boundary.
 */
export class LiveAvatarAudioBridge implements AvatarAudioSink {
  private session: LiveAvatarAudioSession | null = null;
  private video: VolumeTarget | null = null;
  private readonly buffered = new Map<number, BufferedGeneration>();
  private readonly active: ActivePlayback[] = [];
  private volume = 0.8;

  connect(session: LiveAvatarAudioSession, video: VolumeTarget): void {
    this.session = session;
    this.video = video;
    video.volume = this.volume;
  }

  enqueue(chunk: AvatarAudioChunk): boolean {
    if (!this.session || chunk.sampleRateHz !== 24_000) return false;
    const current = this.buffered.get(chunk.generation) ?? {
      clock: new AvatarPlaybackClock(chunk.generation, chunk.speechId),
      chunks: [],
      onStarted: chunk.onStarted,
      onEnded: chunk.onEnded,
    };
    current.clock.append(chunk.pcm16Base64, chunk.sampleRateHz);
    if (chunk.pcm16Base64) current.chunks.push(chunk.pcm16Base64);
    current.onEnded = chunk.onEnded;
    this.buffered.set(chunk.generation, current);
    return true;
  }

  completeGeneration(generation: number): boolean {
    const current = this.buffered.get(generation);
    if (!this.session || !current) return false;
    this.buffered.delete(generation);
    if (current.chunks.length === 0) return false;
    try {
      this.session.repeatAudio(concatenateBase64(current.chunks));
      this.active.push({ generation, clock: current.clock, onEnded: current.onEnded });
      current.clock.start(this.video);
      current.onStarted();
      return true;
    } catch {
      return false;
    }
  }

  handleAvatarSpeechEnded(): void {
    this.active.shift()?.onEnded();
  }

  cancelGeneration(generation: number): void {
    this.buffered.delete(generation);
    const wasActive = this.active.some((playback) => playback.generation === generation);
    for (let index = this.active.length - 1; index >= 0; index -= 1) {
      if (this.active[index]?.generation === generation) this.active.splice(index, 1);
    }
    if (!wasActive || !this.session) return;
    try {
      this.session.interrupt();
    } catch {
      // The renderer may already have disconnected; cancellation is still local.
    }
  }

  playbackPosition(generation: number) {
    return this.active.find(item => item.generation === generation)?.clock.read(this.video) ?? null;
  }

  isActive(generation: number): boolean {
    return this.buffered.has(generation)
      || this.active.some((playback) => playback.generation === generation);
  }

  reset(): void {
    this.buffered.clear();
    this.active.splice(0);
  }

  disconnect(): void {
    this.reset();
    this.session = null;
    this.video = null;
  }

  setVolume(volume: number): void {
    this.volume = Math.max(0, Math.min(1, volume));
    if (this.video) this.video.volume = this.volume;
  }
}

function concatenateBase64(chunks: string[]): string {
  let binary = "";
  for (const chunk of chunks) binary += atob(chunk);
  return btoa(binary);
}

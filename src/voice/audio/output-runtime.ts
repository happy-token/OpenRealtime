import type { PlaybackProgressV2 } from "../protocol/v2";

export interface OutputAudioChunk {
  speechId: string;
  generation: number;
  sequence: number;
  sampleRateHz: number;
  pcm16: Int16Array;
  isFinal: boolean;
}

export class DeviceAudioOutputRuntime {
  private outputEpoch: string | null = null;
  private queue: OutputAudioChunk[] = [];
  private readonly cancelledGenerations = new Set<number>();
  private readonly speechByGeneration = new Map<number, string>();

  get pendingCount(): number {
    return this.queue.length;
  }

  get isActive(): boolean {
    return this.outputEpoch !== null;
  }

  beginEpoch(outputEpoch: string): void {
    if (!outputEpoch) throw new Error("output epoch must be non-empty");
    this.clear();
    this.outputEpoch = outputEpoch;
  }

  enqueue(chunk: OutputAudioChunk): boolean {
    if (this.outputEpoch === null) throw new Error("output epoch is not active");
    if (this.cancelledGenerations.has(chunk.generation)) return false;
    this.speechByGeneration.set(chunk.generation, chunk.speechId);
    this.queue.push({ ...chunk, pcm16: chunk.pcm16.slice() });
    return true;
  }

  takeNext(): OutputAudioChunk | undefined {
    return this.queue.shift();
  }

  cancelGeneration(
    generation: number,
    playedPositionSamples: number,
  ): PlaybackProgressV2 | null {
    if (this.outputEpoch === null) return null;
    const speechId = this.speechByGeneration.get(generation);
    this.cancelledGenerations.add(generation);
    const retained: OutputAudioChunk[] = [];
    for (const chunk of this.queue) {
      if (chunk.generation === generation) chunk.pcm16.fill(0);
      else retained.push(chunk);
    }
    this.queue = retained;
    if (speechId === undefined) return null;
    return this.buildProgress(generation, speechId, "stopped", playedPositionSamples);
  }

  playbackProgress(
    generation: number,
    phase: PlaybackProgressV2["phase"],
    playedPositionSamples: number,
  ): PlaybackProgressV2 | null {
    if (this.outputEpoch === null) return null;
    const speechId = this.speechByGeneration.get(generation);
    if (speechId === undefined) return null;
    return this.buildProgress(generation, speechId, phase, playedPositionSamples);
  }

  private buildProgress(
    generation: number,
    speechId: string,
    phase: PlaybackProgressV2["phase"],
    playedPositionSamples: number,
  ): PlaybackProgressV2 {
    if (this.outputEpoch === null) throw new Error("output epoch is not active");
    return {
      type: "playback_progress_v2",
      output_epoch: this.outputEpoch,
      speech_id: speechId,
      generation,
      phase,
      played_position_samples: Math.max(0, playedPositionSamples),
    };
  }

  reset(): void {
    this.clear();
    this.outputEpoch = null;
  }

  private clear(): void {
    for (const chunk of this.queue) chunk.pcm16.fill(0);
    this.queue = [];
    this.cancelledGenerations.clear();
    this.speechByGeneration.clear();
  }
}

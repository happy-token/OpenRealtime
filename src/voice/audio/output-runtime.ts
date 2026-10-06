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
  private readonly positions = new Map<string, number>();
  private readonly finishedSpeech = new Set<string>();
  private readonly replacedSpeech = new Set<string>();
  private readonly cancelledSpeech = new Set<string>();
  private readonly generationBySpeech = new Map<string, number>();
  private highestGeneration = -1;

  get pendingCount(): number {
    return this.queue.length;
  }

  get isActive(): boolean {
    return this.outputEpoch !== null;
  }

  get currentEpoch(): string | null { return this.outputEpoch; }

  beginEpoch(outputEpoch: string): void {
    if (!outputEpoch) throw new Error("output epoch must be non-empty");
    this.clear();
    this.outputEpoch = outputEpoch;
  }

  canEnqueue(chunk: Pick<OutputAudioChunk, "speechId" | "generation">): boolean {
    if (this.outputEpoch === null) return false;
    if (chunk.generation < this.highestGeneration
      || this.cancelledGenerations.has(chunk.generation)
      || this.finishedSpeech.has(chunk.speechId)
      || this.cancelledSpeech.has(chunk.speechId)
      || this.replacedSpeech.has(chunk.speechId)) return false;
    const boundGeneration = this.generationBySpeech.get(chunk.speechId);
    if (boundGeneration !== undefined && boundGeneration !== chunk.generation) return false;
    return true;
  }

  enqueue(chunk: OutputAudioChunk): boolean {
    if (this.outputEpoch === null) throw new Error("output epoch is not active");
    if (!this.canEnqueue(chunk)) return false;
    const previous = this.speechByGeneration.get(chunk.generation);
    if (previous !== undefined && previous !== chunk.speechId) this.replacedSpeech.add(previous);
    if (chunk.generation > this.highestGeneration) {
      for (const speech of this.speechByGeneration.values()) this.replacedSpeech.add(speech);
    }
    this.highestGeneration = chunk.generation;
    this.generationBySpeech.set(chunk.speechId, chunk.generation);
    this.speechByGeneration.set(chunk.generation, chunk.speechId);
    this.queue = this.queue.filter(queued => {
      if (queued.generation === chunk.generation && queued.speechId === chunk.speechId) return true;
      queued.pcm16.fill(0);
      return false;
    });
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
    if (speechId !== undefined && this.finishedSpeech.has(speechId)) return null;
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

  cancelSpeech(speechId: string, generation: number, playedPositionSamples: number): number | null {
    if (this.outputEpoch === null) return null;
    const bound = this.generationBySpeech.get(speechId);
    if (bound !== undefined && bound !== generation) return null;
    this.generationBySpeech.set(speechId, generation);
    this.cancelledSpeech.add(speechId);
    this.queue = this.queue.filter(chunk => {
      if (chunk.speechId !== speechId) return true;
      chunk.pcm16.fill(0);
      return false;
    });
    const position = Math.max(0, this.positions.get(speechId) ?? 0, playedPositionSamples);
    this.positions.set(speechId, position);
    return position;
  }

  playbackProgress(
    generation: number,
    phase: PlaybackProgressV2["phase"],
    playedPositionSamples: number,
  ): PlaybackProgressV2 | null {
    if (this.outputEpoch === null) return null;
    const speechId = this.speechByGeneration.get(generation);
    if (speechId === undefined) return null;
    if (this.cancelledGenerations.has(generation) && phase !== "stopped") return null;
    if (this.cancelledSpeech.has(speechId) && phase !== "stopped") return null;
    if (this.replacedSpeech.has(speechId) && phase !== "stopped") return null;
    if (this.finishedSpeech.has(speechId) && phase !== "finished") return null;
    if (phase === "finished") this.finishedSpeech.add(speechId);
    return this.buildProgress(generation, speechId, phase, playedPositionSamples);
  }

  private buildProgress(
    generation: number,
    speechId: string,
    phase: PlaybackProgressV2["phase"],
    playedPositionSamples: number,
  ): PlaybackProgressV2 {
    if (this.outputEpoch === null) throw new Error("output epoch is not active");
    const position = Math.max(0, this.positions.get(speechId) ?? 0, playedPositionSamples);
    this.positions.set(speechId, position);
    return {
      type: "playback_progress_v2",
      output_epoch: this.outputEpoch,
      speech_id: speechId,
      generation,
      phase,
      played_position_samples: position,
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
    this.positions.clear();
    this.finishedSpeech.clear();
    this.replacedSpeech.clear();
    this.cancelledSpeech.clear();
    this.generationBySpeech.clear();
    this.highestGeneration = -1;
  }
}

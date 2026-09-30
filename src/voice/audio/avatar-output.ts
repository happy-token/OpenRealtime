export interface AvatarAudioChunk {
  pcm16Base64: string;
  sampleRateHz: number;
  generation: number;
  speechId: string;
  sequence: number;
  isFinal: boolean;
  onStarted: () => void;
  onEnded: () => void;
  /** Replay accepted audio through the browser if the renderer fails asynchronously. */
  onFallback?: (isFinal: boolean) => void;
}

/** Optional renderer sink. Returning false keeps the normal browser audio path. */
export interface AvatarAudioSink {
  enqueue(chunk: AvatarAudioChunk): boolean;
  completeGeneration(generation: number): boolean;
  cancelGeneration(generation: number): void;
  isActive(generation: number): boolean;
  reset(): void;
  setVolume(volume: number): void;
}

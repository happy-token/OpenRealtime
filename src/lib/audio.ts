// Pure audio-encoding helpers ported verbatim from clients/web/app.js.
// Kept dependency-free and side-effect-free so they're unit-testable
// without a DOM/AudioContext (see lib/audio.test.ts).

export const MIC_SAMPLE_RATE_HZ = 16000;
export const LOCAL_MIC_CHUNK_MS = 32;
export const LOCAL_MIC_CHUNK_SAMPLES = MIC_SAMPLE_RATE_HZ * LOCAL_MIC_CHUNK_MS / 1000;

export function arrayBufferToBase64(buffer: ArrayBuffer): string {
  let binary = "";
  const bytes = new Uint8Array(buffer);
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

export function base64ToInt16Array(base64: string): Int16Array {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return new Int16Array(bytes.buffer);
}

export function readAnalyserLevel(analyser: AnalyserNode, buffer: Uint8Array<ArrayBuffer>): number {
  analyser.getByteTimeDomainData(buffer);
  let sumSquares = 0;
  for (let i = 0; i < buffer.length; i++) {
    const normalized = (buffer[i] - 128) / 128;
    sumSquares += normalized * normalized;
  }
  return Math.sqrt(sumSquares / buffer.length);
}

export interface PlaybackQuality {
  generation: number;
  arrivalJitterMs: number;
  maxChunkGapMs: number;
  underrunCount: number;
  underrunTotalMs: number;
  chunkCount: number;
  lastArrivalMs: number | null;
  previousChunkDurationMs: number | null;
  jitterSampleCount: number;
}

export function createPlaybackQuality(generation: number): PlaybackQuality {
  return {
    generation,
    arrivalJitterMs: 0,
    maxChunkGapMs: 0,
    underrunCount: 0,
    underrunTotalMs: 0,
    chunkCount: 0,
    lastArrivalMs: null,
    previousChunkDurationMs: null,
    jitterSampleCount: 0,
  };
}

export function observePlaybackChunk(
  quality: PlaybackQuality,
  observation: { arrivedAtMs: number; chunkDurationMs: number; underrunMs: number },
): PlaybackQuality {
  const intervalMs = quality.lastArrivalMs === null
    ? null
    : Math.max(0, observation.arrivedAtMs - quality.lastArrivalMs);
  const deviationMs = intervalMs === null || quality.previousChunkDurationMs === null
    ? null
    : Math.abs(intervalMs - quality.previousChunkDurationMs);
  const jitterSampleCount = quality.jitterSampleCount + (deviationMs === null ? 0 : 1);
  const arrivalJitterMs = deviationMs === null
    ? quality.arrivalJitterMs
    : (
        quality.arrivalJitterMs * quality.jitterSampleCount + deviationMs
      ) / jitterSampleCount;
  const underrunMs = Math.max(0, observation.underrunMs);
  return {
    ...quality,
    arrivalJitterMs,
    maxChunkGapMs: Math.max(quality.maxChunkGapMs, intervalMs ?? 0),
    underrunCount: quality.underrunCount + (underrunMs > 0 ? 1 : 0),
    underrunTotalMs: quality.underrunTotalMs + underrunMs,
    chunkCount: quality.chunkCount + 1,
    lastArrivalMs: observation.arrivedAtMs,
    previousChunkDurationMs: Math.max(0, observation.chunkDurationMs),
    jitterSampleCount,
  };
}

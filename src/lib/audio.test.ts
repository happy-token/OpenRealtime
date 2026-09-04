import { describe, expect, it } from "vitest";
import {
  arrayBufferToBase64,
  base64ToInt16Array,
  createPlaybackQuality,
  LOCAL_MIC_CHUNK_MS,
  LOCAL_MIC_CHUNK_SAMPLES,
  MIC_SAMPLE_RATE_HZ,
  observePlaybackChunk,
  readAnalyserLevel,
} from "./audio";

describe("microphone framing", () => {
  it("sends one 32ms Silero window per local WebSocket packet", () => {
    expect(MIC_SAMPLE_RATE_HZ).toBe(16000);
    expect(LOCAL_MIC_CHUNK_MS).toBe(32);
    expect(LOCAL_MIC_CHUNK_SAMPLES).toBe(512);
  });
});

describe("arrayBufferToBase64 / base64ToInt16Array", () => {
  it("round-trips an Int16Array through base64", () => {
    const original = new Int16Array([0, 1, -1, 32767, -32768, 12345]);

    const encoded = arrayBufferToBase64(original.buffer);
    const decoded = base64ToInt16Array(encoded);

    expect(Array.from(decoded)).toEqual(Array.from(original));
  });

  it("round-trips an empty buffer", () => {
    const original = new Int16Array([]);

    const encoded = arrayBufferToBase64(original.buffer);
    const decoded = base64ToInt16Array(encoded);

    expect(decoded.length).toBe(0);
  });
});

describe("readAnalyserLevel", () => {
  it("returns 0 for silence (all samples at the 128 midpoint)", () => {
    const buffer = new Uint8Array(8).fill(128);
    const analyser = {
      getByteTimeDomainData: (out: Uint8Array) => out.set(buffer),
    } as unknown as AnalyserNode;

    const level = readAnalyserLevel(analyser, buffer);

    expect(level).toBe(0);
  });

  it("returns 1 for full-scale samples", () => {
    const buffer = new Uint8Array(4).fill(255);
    const analyser = {
      getByteTimeDomainData: (out: Uint8Array) => out.set(buffer),
    } as unknown as AnalyserNode;

    const level = readAnalyserLevel(analyser, buffer);

    expect(level).toBeCloseTo(127 / 128, 5);
  });
});

describe("playback quality aggregation", () => {
  it("summarizes arrival jitter and audible underruns without retaining chunk data", () => {
    let quality = createPlaybackQuality(7);
    quality = observePlaybackChunk(quality, { arrivedAtMs: 0, chunkDurationMs: 40, underrunMs: 0 });
    quality = observePlaybackChunk(quality, { arrivedAtMs: 55, chunkDurationMs: 40, underrunMs: 18 });
    quality = observePlaybackChunk(quality, { arrivedAtMs: 105, chunkDurationMs: 40, underrunMs: 0 });

    expect(quality).toEqual(expect.objectContaining({
      generation: 7,
      arrivalJitterMs: 12.5,
      maxChunkGapMs: 55,
      underrunCount: 1,
      underrunTotalMs: 18,
      chunkCount: 3,
    }));
    expect(JSON.stringify(quality)).not.toContain("pcm");
  });
});

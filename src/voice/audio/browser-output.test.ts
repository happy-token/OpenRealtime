import { describe, expect, it, vi } from "vitest";

import { DeviceAudioOutputRuntime } from "./output-runtime";
import { BrowserAudioOutput } from "./browser-output";

function fakeContext() {
  const sources: Array<{
    start: ReturnType<typeof vi.fn>;
    stop: ReturnType<typeof vi.fn>;
    ended: (() => void) | null;
  }> = [];
  const gain = { gain: { value: 0 }, connect: vi.fn() };
  const analyser = {
    fftSize: 0,
    connect: vi.fn(),
    getByteTimeDomainData: vi.fn((buffer: Uint8Array) => buffer.fill(128)),
  };
  const context = {
    currentTime: 1,
    destination: {},
    createGain: () => gain,
    createAnalyser: () => analyser,
    createBuffer: (_channels: number, length: number, sampleRate: number) => ({
      duration: length / sampleRate,
      copyToChannel: vi.fn(),
    }),
    createBufferSource: () => {
      const source = {
        buffer: null,
        connect: vi.fn(),
        start: vi.fn(),
        stop: vi.fn(),
        ended: null as (() => void) | null,
        addEventListener: (_type: "ended", listener: () => void) => {
          source.ended = listener;
        },
      };
      sources.push(source);
      return source;
    },
    close: vi.fn(),
  };
  return { context, gain, sources };
}

describe("BrowserAudioOutput", () => {
  it("restores playback after ending a conversation without a new handshake", () => {
    const fake = fakeContext();
    const runtime = new DeviceAudioOutputRuntime();
    const output = new BrowserAudioOutput({
      runtime,
      createContext: () => fake.context as unknown as AudioContext,
    });
    const chunk = {
      pcm16Base64: "AAAAAA==",
      sampleRateHz: 16_000,
      generation: 3,
      speechId: "speech-3",
      sequence: 0,
      isFinal: true,
    };

    output.activate();
    expect(output.play(chunk)).toBe(true);
    const firstEpoch = output.playbackProgress(3, "started")?.output_epoch;
    expect(firstEpoch).toBeTruthy();
    output.reset();
    expect(runtime.isActive).toBe(false);
    expect(fake.sources[0].stop).toHaveBeenCalledOnce();

    output.activate();
    expect(output.play({ ...chunk, generation: 4, speechId: "speech-4" })).toBe(true);
    expect(fake.sources[1].start).toHaveBeenCalledOnce();
    const nextEpoch = output.playbackProgress(4, "started")?.output_epoch;
    expect(nextEpoch).toBeTruthy();
    expect(nextEpoch).not.toBe(firstEpoch);
  });

  it("preserves the current epoch and cancelled generations when activated again", () => {
    const fake = fakeContext();
    const output = new BrowserAudioOutput({
      runtime: new DeviceAudioOutputRuntime(),
      createContext: () => fake.context as unknown as AudioContext,
    });
    const chunk = {
      pcm16Base64: "AAAAAA==",
      sampleRateHz: 16_000,
      generation: 3,
      speechId: "speech-3",
      sequence: 0,
      isFinal: true,
    };
    output.beginEpoch("output-1");
    output.play(chunk);
    output.cancelGeneration(3);
    output.activate();

    expect(output.play(chunk)).toBe(false);
    expect(output.playbackProgress(3, "stopped")?.output_epoch).toBe("output-1");
    expect(fake.sources).toHaveLength(1);
  });

  it("assembles the graph once and schedules chunks without gaps", () => {
    const fake = fakeContext();
    const started: number[] = [];
    const runtime = new DeviceAudioOutputRuntime();
    runtime.beginEpoch("output-1");
    const output = new BrowserAudioOutput({
      runtime,
      createContext: () => fake.context as unknown as AudioContext,
      onStarted: (generation) => started.push(generation),
    });

    output.play({
      pcm16Base64: "AAAAAA==",
      sampleRateHz: 16_000,
      generation: 3,
      speechId: "speech-3",
      sequence: 0,
      isFinal: false,
    });
    output.play({
      pcm16Base64: "AAAAAA==",
      sampleRateHz: 16_000,
      generation: 3,
      speechId: "speech-3",
      sequence: 1,
      isFinal: true,
    });

    expect(started).toEqual([3]);
    expect(fake.gain.gain.value).toBe(0.8);
    expect(fake.sources).toHaveLength(2);
    expect(fake.sources[0].start).toHaveBeenCalledWith(1);
    expect(fake.sources[1].start).toHaveBeenCalledWith(1.000125);
    expect(output.scheduledSourceCount).toBe(2);
  });

  it("stops an interrupted generation and returns v2 playback truth", () => {
    const fake = fakeContext();
    const runtime = new DeviceAudioOutputRuntime();
    runtime.beginEpoch("output-1");
    const output = new BrowserAudioOutput({
      runtime,
      createContext: () => fake.context as unknown as AudioContext,
    });
    output.play({
      pcm16Base64: "AAAAAA==",
      sampleRateHz: 16_000,
      generation: 4,
      speechId: "speech-4",
      sequence: 0,
      isFinal: true,
    });

    fake.context.currentTime = 1.000125;
    const progress = output.cancelGeneration(4);

    expect(progress).toMatchObject({
      type: "playback_progress_v2",
      output_epoch: "output-1",
      speech_id: "speech-4",
      generation: 4,
      phase: "stopped",
      played_position_samples: 2,
    });
    expect(fake.sources[0].stop).toHaveBeenCalledOnce();
    expect(output.scheduledSourceCount).toBe(0);
  });
});

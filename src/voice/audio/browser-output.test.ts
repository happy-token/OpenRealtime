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

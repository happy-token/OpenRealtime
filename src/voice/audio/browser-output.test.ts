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
    state: "suspended",
    resume: vi.fn(async () => {
      context.state = "running";
    }),
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
  it.each([1, 2])("ignores old speech audio after a replacement on generation %i", (generation) => {
    const fake = fakeContext();
    const output = new BrowserAudioOutput({ runtime: new DeviceAudioOutputRuntime(),
      createContext: () => fake.context as unknown as AudioContext });
    output.beginEpoch("epoch");
    const old = { pcm16Base64: "AAAAAA==", sampleRateHz: 16000, generation: 1,
      speechId: "old", sequence: 0, isFinal: false };
    output.play(old);
    output.play({ ...old, generation, speechId: "new" });
    expect(output.play({ ...old, sequence: 1 })).toBe(false);
    expect(fake.sources).toHaveLength(2);
    expect(fake.sources[1].stop).not.toHaveBeenCalled();
    expect(output.activeGeneration).toBe(generation);
    expect(output.playbackProgress(generation, "playing")?.speech_id).toBe("new");
    output.close();
  });

  it("does not report a natural completion after a source was cancelled", () => {
    const fake = fakeContext();
    const ended = vi.fn();
    const output = new BrowserAudioOutput({runtime: new DeviceAudioOutputRuntime(),
      createContext: () => fake.context as unknown as AudioContext});
    output.beginEpoch("epoch");
    output.play({pcm16Base64: "AAAAAA==", sampleRateHz: 16_000, generation: 1,
      speechId: "old", sequence: 0, isFinal: true, onEnded: ended});
    output.cancelGeneration(1);
    fake.sources[0].ended?.();
    expect(ended).not.toHaveBeenCalled();
    expect(output.finishGeneration(1)).toBeNull();
    output.close();
  });

  it("a late cancellation of an old generation preserves newer audio and its clock", () => {
    const fake = fakeContext();
    const output = new BrowserAudioOutput({runtime: new DeviceAudioOutputRuntime(),
      createContext: () => fake.context as unknown as AudioContext});
    output.beginEpoch("epoch");
    const chunk = {pcm16Base64: "AAAAAA==", sampleRateHz: 16_000, generation: 1,
      speechId: "old", sequence: 0, isFinal: true};
    output.play(chunk);
    fake.context.currentTime = 1.000125;
    output.play({...chunk, generation: 2, speechId: "new"});
    fake.context.currentTime = 1.00025;
    const old = output.cancelGeneration(1);
    expect(fake.sources[1].stop).not.toHaveBeenCalled();
    expect(output.activeGeneration).toBe(2);
    expect(output.scheduledSourceCount).toBe(1);
    expect(old).toMatchObject({speech_id: "old", played_position_samples: 2, phase: "stopped"});
    expect(output.playbackProgress(2, "playing")).toMatchObject({speech_id: "new", played_position_samples: 2});
    output.close();
  });

  it("starts a new epoch by stopping old audio and suppressing its delayed completion", () => {
    const fake = fakeContext();
    const ended = vi.fn();
    const output = new BrowserAudioOutput({runtime: new DeviceAudioOutputRuntime(),
      createContext: () => fake.context as unknown as AudioContext});
    const chunk = {pcm16Base64: "AAAAAA==", sampleRateHz: 16_000, generation: 1,
      speechId: "old", sequence: 0, isFinal: true, onEnded: ended};
    output.beginEpoch("old-epoch");
    output.play(chunk);
    output.beginEpoch("new-epoch");
    expect(fake.sources[0].stop).toHaveBeenCalledOnce();
    output.play({...chunk, speechId: "new"});
    fake.sources[0].ended?.();
    expect(ended).not.toHaveBeenCalled();
    expect(output.playbackProgress(1, "playing")?.output_epoch).toBe("new-epoch");
    output.close();
  });

  it("keeps distinct speech clocks when a generation is reused or the sample rate changes", () => {
    const fake = fakeContext();
    const ended = vi.fn();
    const output = new BrowserAudioOutput({runtime: new DeviceAudioOutputRuntime(),
      createContext: () => fake.context as unknown as AudioContext});
    output.beginEpoch("epoch");
    const chunk = {pcm16Base64: "AAAAAA==", sampleRateHz: 16000, generation: 1,
      speechId: "first", sequence: 0, isFinal: true, onEnded: ended};
    output.play(chunk);
    fake.context.currentTime = 1.000125;
    output.play({...chunk, sampleRateHz: 24000, speechId: "second"});
    fake.sources[0].ended?.();
    expect(ended).not.toHaveBeenCalled();
    expect(fake.sources[0].stop).toHaveBeenCalledOnce();
    expect(output.playbackProgress(1, "started")).toMatchObject({speech_id: "second", played_position_samples: 0});
    output.close();
  });

  it("resumes browser audio during the start gesture", async () => {
    const fake = fakeContext();
    const output = new BrowserAudioOutput({
      runtime: new DeviceAudioOutputRuntime(),
      createContext: () => fake.context as unknown as AudioContext,
    });

    await output.unlock();
    expect(fake.context.resume).toHaveBeenCalledOnce();
    expect(fake.context.state).toBe("running");
  });

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
    const resumed: number[] = [];
    const runtime = new DeviceAudioOutputRuntime();
    runtime.beginEpoch("output-1");
    const output = new BrowserAudioOutput({
      runtime,
      createContext: () => fake.context as unknown as AudioContext,
      onStarted: (generation) => started.push(generation),
      onResumed: (generation) => resumed.push(generation),
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
    expect(resumed).toEqual([]);
    expect(fake.gain.gain.value).toBe(0.8);
    expect(fake.sources).toHaveLength(2);
    expect(fake.sources[0].start).toHaveBeenCalledWith(1);
    expect(fake.sources[1].start).toHaveBeenCalledWith(1.000125);
    expect(output.scheduledSourceCount).toBe(2);
  });

  it("notifies when a later TTS chunk resumes after the playback queue drains", () => {
    const fake = fakeContext();
    const started = vi.fn();
    const resumed = vi.fn();
    const runtime = new DeviceAudioOutputRuntime();
    runtime.beginEpoch("output-1");
    const output = new BrowserAudioOutput({
      runtime,
      createContext: () => fake.context as unknown as AudioContext,
      onStarted: started,
      onResumed: resumed,
    });
    const chunk = {
      pcm16Base64: "AAAAAA==",
      sampleRateHz: 16_000,
      generation: 3,
      speechId: "speech-3",
      sequence: 0,
      isFinal: false,
    };

    expect(output.play(chunk)).toBe(true);
    fake.sources[0].ended?.();
    expect(output.scheduledSourceCount).toBe(0);
    expect(output.play({ ...chunk, sequence: 1, isFinal: true })).toBe(true);

    expect(started).toHaveBeenCalledOnce();
    expect(resumed).toHaveBeenCalledExactlyOnceWith(3);
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

it("reports ongoing playback and excludes weak-network gaps from sample position", () => {
  vi.useFakeTimers();
  const fake = fakeContext();
  fake.context.state = "running";
  const onProgress = vi.fn();
  const output = new BrowserAudioOutput({
    runtime: new DeviceAudioOutputRuntime(),
    createContext: () => fake.context as unknown as AudioContext,
    onProgress,
  });
  try {
    output.beginEpoch("epoch");
    const chunk = { pcm16Base64: "AAAAAA==", sampleRateHz: 16_000, generation: 1, speechId: "s", sequence: 0, isFinal: false };
    output.play(chunk);
    fake.context.currentTime = 2; // one second network gap, two samples actually played
    fake.sources[0].ended?.();
    output.play({ ...chunk, sequence: 1 });
    fake.context.currentTime = 2.000125;
    vi.advanceTimersByTime(100);
    expect(onProgress).toHaveBeenCalledWith(expect.objectContaining({ phase: "playing", played_position_samples: 4 }));
    output.reset();
    onProgress.mockClear();
    vi.advanceTimersByTime(200);
    expect(onProgress).not.toHaveBeenCalled();
  } finally {
    output.close();
    vi.useRealTimers();
  }
});

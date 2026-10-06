import { describe, expect, it } from "vitest";

import { DeviceAudioOutputRuntime } from "./output-runtime";


describe("DeviceAudioOutputRuntime", () => {
  it("allows another speech on the same input generation after natural completion", () => {
    const runtime = new DeviceAudioOutputRuntime();
    runtime.beginEpoch("epoch");
    const chunk = {speechId: "first", generation: 1, sequence: 0,
      sampleRateHz: 16000, pcm16: new Int16Array(2), isFinal: true};
    runtime.enqueue(chunk);
    runtime.playbackProgress(1, "finished", 2);
    expect(runtime.cancelGeneration(1, 2)).toBeNull();
    expect(runtime.enqueue({...chunk, speechId: "second"})).toBe(true);
    expect(runtime.playbackProgress(1, "started", 0)).toMatchObject({speech_id: "second", played_position_samples: 0});
  });
  it("clears a cancelled generation and rejects every late chunk for it", () => {
    const runtime = new DeviceAudioOutputRuntime();
    runtime.beginEpoch("output-1");
    expect(runtime.enqueue({
      speechId: "speech-7",
      generation: 7,
      sequence: 0,
      sampleRateHz: 16_000,
      pcm16: new Int16Array(512),
      isFinal: false,
    })).toBe(true);

    const progress = runtime.cancelGeneration(7, 256);

    expect(progress).toEqual({
      type: "playback_progress_v2",
      output_epoch: "output-1",
      speech_id: "speech-7",
      generation: 7,
      phase: "stopped",
      played_position_samples: 256,
    });
    expect(runtime.pendingCount).toBe(0);
    expect(runtime.enqueue({
      speechId: "speech-7",
      generation: 7,
      sequence: 1,
      sampleRateHz: 16_000,
      pcm16: new Int16Array(512),
      isFinal: true,
    })).toBe(false);
    expect(runtime.enqueue({
      speechId: "speech-8",
      generation: 8,
      sequence: 0,
      sampleRateHz: 16_000,
      pcm16: new Int16Array(512),
      isFinal: true,
    })).toBe(true);
  });

  it("reports exact start and finish positions for the active speech", () => {
    const runtime = new DeviceAudioOutputRuntime();
    runtime.beginEpoch("output-1");
    runtime.enqueue({
      speechId: "speech-1",
      generation: 4,
      sequence: 0,
      sampleRateHz: 24_000,
      pcm16: new Int16Array([1, 2]),
      isFinal: true,
    });

    expect(runtime.playbackProgress(4, "started", 0)?.phase).toBe("started");
    expect(runtime.playbackProgress(4, "finished", 2)).toMatchObject({
      output_epoch: "output-1",
      speech_id: "speech-1",
      phase: "finished",
      played_position_samples: 2,
    });
  });
});

import { describe, expect, it } from "vitest";

import { DEFAULT_DEVICE_CAPTURE_PROFILE } from "../protocol/v2";
import { DeviceAudioInputRuntime } from "./input-runtime";


function profile(overrides: Partial<typeof DEFAULT_DEVICE_CAPTURE_PROFILE> = {}) {
  return { ...DEFAULT_DEVICE_CAPTURE_PROFILE, ...overrides };
}

describe("DeviceAudioInputRuntime", () => {
  it("records the negotiated capture graph and timeline origin for every epoch", () => {
    const runtime = new DeviceAudioInputRuntime({ now: () => 123.5 });

    expect(runtime.beginEpoch("input-1", {
      requestedConstraints: {
        echo_cancellation: true,
        noise_suppression: true,
        auto_gain_control: true,
      },
      effectiveConstraints: {
        echo_cancellation: true,
        noise_suppression: false,
        auto_gain_control: true,
      },
      effectOwners: {
        echo_cancellation: "device",
        noise_suppression: "none",
        auto_gain_control: "device",
      },
    })).toMatchObject({
      timeline_origin_ms: 123.5,
      effective_constraints: { noise_suppression: false },
      effect_owners: { noise_suppression: "none" },
    });
  });

  it("keeps one ordered sample timeline while buffered audio catches up with live capture", () => {
    const runtime = new DeviceAudioInputRuntime({
      profile: profile({ queue_high_watermark: 8, queue_low_watermark: 2 }),
      maxBufferFrames: 8,
      now: () => 0,
    });
    runtime.beginEpoch("input-1");
    runtime.pushFrame(new Int16Array(512).fill(1));
    runtime.pushFrame(new Int16Array(512).fill(2));

    expect(runtime.state).toBe("buffering");
    expect(runtime.drain(8, 0)).toEqual([]);

    runtime.release("input-1", 0);
    runtime.pushFrame(new Int16Array(512).fill(3), "live");
    const frames = runtime.drain(8, 32);

    expect(frames.map((frame) => ({
      sequence: frame.sequence,
      startSample: frame.start_sample,
      captureMode: frame.capture_mode,
    }))).toEqual([
      { sequence: 0, startSample: 0, captureMode: "prebuffer" },
      { sequence: 1, startSample: 512, captureMode: "prebuffer" },
      { sequence: 2, startSample: 1024, captureMode: "live" },
    ]);
    expect(runtime.state).toBe("live");
  });

  it("paces replay at no more than the configured accelerated rate", () => {
    const runtime = new DeviceAudioInputRuntime({
      profile: profile({
        frame_duration_ms: 32,
        max_replay_rate: 2,
        queue_high_watermark: 16,
        queue_low_watermark: 4,
      }),
      now: () => 0,
    });
    runtime.beginEpoch("input-1");
    for (let index = 0; index < 8; index += 1) {
      runtime.pushFrame(new Int16Array(512).fill(index + 1));
    }
    runtime.release("input-1", 0);

    expect(runtime.drain(20, 0)).toHaveLength(1);
    expect(runtime.drain(20, 15)).toHaveLength(0);
    expect(runtime.drain(20, 16)).toHaveLength(1);
    expect(runtime.drain(20, 32)).toHaveLength(1);
  });

  it("uses cumulative ACKs and high/low watermarks for downstream backpressure", () => {
    const runtime = new DeviceAudioInputRuntime({
      profile: profile({
        max_replay_rate: 2,
        queue_low_watermark: 1,
        queue_high_watermark: 3,
      }),
      now: () => 0,
    });
    runtime.beginEpoch("input-1");
    for (let index = 0; index < 6; index += 1) {
      runtime.pushFrame(new Int16Array(512).fill(index + 1));
    }
    runtime.release("input-1", 0);

    expect(runtime.drain(20, 64)).toHaveLength(3);
    expect(runtime.backpressured).toBe(true);
    expect(runtime.drain(20, 96)).toEqual([]);

    expect(runtime.acknowledge({
      type: "input_audio_ack",
      input_epoch: "input-1",
      highest_contiguous_sequence: 0,
      next_start_sample: 512,
    })).toBe(true);
    expect(runtime.backpressured).toBe(true);

    expect(runtime.acknowledge({
      type: "input_audio_ack",
      input_epoch: "input-1",
      highest_contiguous_sequence: 1,
      next_start_sample: 1024,
    })).toBe(true);
    expect(runtime.backpressured).toBe(false);
    expect(runtime.drain(20, 96)).toHaveLength(2);
  });

  it("ignores stale ACKs and rejects impossible cumulative ACK positions", () => {
    const runtime = new DeviceAudioInputRuntime({ now: () => 0 });
    runtime.beginEpoch("input-1");
    runtime.pushFrame(new Int16Array(512).fill(1));
    runtime.release("input-1", 0);
    runtime.drain(1, 0);

    expect(runtime.acknowledge({
      type: "input_audio_ack",
      input_epoch: "old-input",
      highest_contiguous_sequence: 0,
      next_start_sample: 512,
    })).toBe(false);
    expect(() => runtime.acknowledge({
      type: "input_audio_ack",
      input_epoch: "input-1",
      highest_contiguous_sequence: 2,
      next_start_sample: 1536,
    })).toThrow("ACK exceeds sent input audio");
  });

  it("invalidates the epoch when a 1x downstream cannot catch up by its deadline", () => {
    const runtime = new DeviceAudioInputRuntime({
      profile: profile({
        max_replay_rate: 1,
        catchup_deadline_ms: 64,
        queue_high_watermark: 8,
        queue_low_watermark: 2,
      }),
      now: () => 0,
    });
    runtime.beginEpoch("input-1");
    runtime.pushFrame(new Int16Array(512).fill(1));
    runtime.pushFrame(new Int16Array(512).fill(2));
    runtime.release("input-1", 0);
    runtime.pushFrame(new Int16Array(512).fill(3), "live");

    expect(() => runtime.drain(8, 65)).toThrow("input catch-up deadline exceeded");
    expect(runtime.state).toBe("reset");
    expect(runtime.lastFailure).toEqual({ inputEpoch: "input-1", bufferedFrames: 3 });
    expect(runtime.drain(8, 100)).toEqual([]);
  });

  it("invalidates the entire epoch instead of sending a truncated voiced tail", () => {
    const runtime = new DeviceAudioInputRuntime({ maxBufferFrames: 2 });
    runtime.beginEpoch("input-1");
    runtime.pushFrame(new Int16Array(512).fill(1));
    runtime.pushFrame(new Int16Array(512).fill(2));

    expect(() => runtime.pushFrame(new Int16Array(512).fill(3))).toThrow(
      "input epoch overflow",
    );
    expect(runtime.state).toBe("reset");
    expect(runtime.lastFailure).toEqual({ inputEpoch: "input-1", bufferedFrames: 2 });
    expect(runtime.drain(8)).toEqual([]);
  });
});

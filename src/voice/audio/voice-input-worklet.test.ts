import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
import { describe, expect, it } from "vitest";


interface PostedMessage {
  type: string;
  captureMode?: string;
  pcm16?: ArrayBuffer;
  inputEpoch?: string;
  bufferedFrames?: number;
  aggregateEnergy?: number;
}

interface WorkletProcessor {
  port: { onmessage: ((event: { data: unknown }) => void) | null };
  process: (inputs: Float32Array[][]) => boolean;
}

function createProcessor(options: Record<string, unknown> = {}) {
  const posted: PostedMessage[] = [];
  let Processor: (new (options?: unknown) => WorkletProcessor) | undefined;
  class FakeAudioWorkletProcessor {
    port = {
      onmessage: null as ((event: { data: unknown }) => void) | null,
      postMessage: (message: PostedMessage) => posted.push(message),
    };
  }

  runInNewContext(
    readFileSync(new URL("../../../public/voice-input-worklet.js", import.meta.url), "utf8"),
    {
      AudioWorkletProcessor: FakeAudioWorkletProcessor,
      Float32Array,
      Int16Array,
      Math,
      Number,
      sampleRate: 16000,
      registerProcessor: (_name: string, implementation: NonNullable<typeof Processor>) => {
        Processor = implementation;
      },
    },
  );

  if (!Processor) throw new Error("worklet did not register a processor");
  return {
    posted,
    processor: new Processor({
      processorOptions: {
        inputEpoch: "input-1",
        flushSampleCount: 512,
        maxBufferFrames: 8,
        silenceThreshold: 0.003,
        preRollFrames: 2,
        ...options,
      },
    }),
  };
}

function audioMessages(posted: PostedMessage[]) {
  return posted.filter((message) => message.type === "audio_frame");
}

function peak(message: PostedMessage) {
  if (!message.pcm16) return 0;
  return Math.max(...new Int16Array(message.pcm16).map((sample) => Math.abs(sample)));
}

describe("voice input worklet", () => {
  it("trims leading silence but preserves the configured pre-roll before first speech", () => {
    const { posted, processor } = createProcessor();
    processor.process([[new Float32Array(513).fill(0)]]);
    processor.process([[new Float32Array(512).fill(0)]]);
    processor.process([[new Float32Array(512).fill(0)]]);
    processor.process([[new Float32Array(512).fill(0.1)]]);

    processor.port.onmessage?.({ data: { type: "release", input_epoch: "input-1" } });
    processor.process([[new Float32Array(512).fill(0.2)]]);
    processor.process([[new Float32Array(512).fill(0.2)]]);

    const audio = audioMessages(posted);
    expect(audio.length).toBeGreaterThanOrEqual(4);
    expect(audio.slice(0, 4).map((message) => message.captureMode)).toEqual([
      "prebuffer",
      "prebuffer",
      "prebuffer",
      "live",
    ]);
    expect(audio.slice(0, 4).map(peak)).toEqual([0, 0, 3276, 6553]);
  });

  it("buffers before release and keeps concurrent live samples behind replayed samples", () => {
    const { posted, processor } = createProcessor();
    processor.process([[new Float32Array(1025).fill(0.1)]]);
    expect(posted).toEqual([]);

    processor.port.onmessage?.({ data: { type: "release", input_epoch: "input-1" } });
    processor.process([[new Float32Array(512).fill(0.2)]]);
    processor.process([[new Float32Array(512).fill(0.3)]]);

    const audio = audioMessages(posted);
    expect(audio.map((message) => message.captureMode)).toEqual([
      "prebuffer",
      "prebuffer",
      "live",
      "live",
    ]);
    expect(audio.every((message) => message.pcm16?.byteLength === 1024)).toBe(true);
    expect(audio.map(peak)).toEqual([3276, 3276, 6553, 9830]);
  });

  it("retains live audio while ACK backpressure pauses downstream delivery", () => {
    const { posted, processor } = createProcessor();
    processor.port.onmessage?.({ data: { type: "release", input_epoch: "input-1" } });
    processor.port.onmessage?.({ data: { type: "downstream_pause", input_epoch: "input-1" } });
    processor.process([[new Float32Array(1025).fill(0.1)]]);
    expect(audioMessages(posted)).toEqual([]);

    processor.port.onmessage?.({ data: { type: "downstream_resume", input_epoch: "input-1" } });
    processor.process([[new Float32Array(512).fill(0.2)]]);
    processor.process([[new Float32Array(512).fill(0.2)]]);

    expect(audioMessages(posted).map((message) => message.captureMode)).toEqual([
      "live",
      "live",
      "live",
      "live",
    ]);
  });

  it("clears the epoch and emits content-free evidence on bounded-buffer overflow", () => {
    const { posted, processor } = createProcessor({ maxBufferFrames: 2, preRollFrames: 0 });
    processor.process([[new Float32Array(1537).fill(0.1)]]);

    const overflow = posted.find((message) => message.type === "overflow");
    expect(overflow).toMatchObject({
      type: "overflow",
      inputEpoch: "input-1",
      bufferedFrames: 2,
    });
    expect(overflow?.aggregateEnergy).toBeGreaterThan(0);
    processor.port.onmessage?.({ data: { type: "release", input_epoch: "input-1" } });
    processor.process([[new Float32Array(512).fill(0.2)]]);
    expect(audioMessages(posted)).toEqual([]);
  });

  it("rejects stale release and never joins PCM across an epoch reset", () => {
    const { posted, processor } = createProcessor();
    processor.process([[new Float32Array(513).fill(0.1)]]);
    processor.port.onmessage?.({ data: { type: "begin_epoch", input_epoch: "input-2" } });
    processor.port.onmessage?.({ data: { type: "release", input_epoch: "input-1" } });
    processor.process([[new Float32Array(512).fill(0.2)]]);
    expect(audioMessages(posted)).toEqual([]);

    processor.port.onmessage?.({ data: { type: "release", input_epoch: "input-2" } });
    processor.process([[new Float32Array(512).fill(0.3)]]);
    processor.process([[new Float32Array(512).fill(0.3)]]);

    const audio = audioMessages(posted);
    expect(audio.every((message) => message.inputEpoch === "input-2")).toBe(true);
    expect(audio.every((message) => peak(message) >= 6553)).toBe(true);
  });
});

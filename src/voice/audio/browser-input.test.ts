import { describe, expect, it, vi } from "vitest";

import { DeviceAudioInputRuntime } from "./input-runtime";
import { BrowserAudioInput } from "./browser-input";
import { DeviceAudioOutputRuntime } from "./output-runtime";
import { ClientVoiceSessionController } from "../session/controller";

function fixture() {
  const sent: Array<{ type: string; [key: string]: unknown }> = [];
  const track = {
    stop: vi.fn(),
    getSettings: () => ({
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    }),
    addEventListener: vi.fn(),
  };
  const stream = {
    getAudioTracks: () => [track],
    getTracks: () => [track],
  };
  const source = { connect: vi.fn() };
  const analyser = {
    fftSize: 0,
    getByteTimeDomainData: vi.fn((buffer: Uint8Array) => buffer.fill(128)),
  };
  const context = {
    state: "running",
    audioWorklet: { addModule: vi.fn().mockResolvedValue(undefined) },
    createMediaStreamSource: () => source,
    createAnalyser: () => analyser,
    close: vi.fn(),
    onstatechange: null as (() => void) | null,
  };
  const port = {
    onmessage: null as ((event: MessageEvent) => void) | null,
    postMessage: vi.fn(),
  };
  const worklet = {
    port,
    onprocessorerror: null as (() => void) | null,
    disconnect: vi.fn(),
  };
  const runtime = new DeviceAudioInputRuntime();
  const controller = new ClientVoiceSessionController({
    input: runtime,
    output: new DeviceAudioOutputRuntime(),
  });
  const input = new BrowserAudioInput({
    runtime,
    controller,
    isTransportOpen: () => true,
    send: (frame) => {
      sent.push(frame as unknown as { type: string; [key: string]: unknown });
      return true;
    },
    getNoiseSuppression: () => true,
    shouldDropFrame: () => false,
    onFailure: vi.fn(),
    onCaptureStopped: vi.fn(),
    getUserMedia: vi.fn().mockResolvedValue(stream as unknown as MediaStream),
    createContext: () => context as unknown as AudioContext,
    createWorklet: () => worklet as unknown as AudioWorkletNode,
    createInputEpoch: () => "input-1",
  });
  return { input, runtime, sent, source, worklet, track, context };
}

describe("BrowserAudioInput", () => {
  it("assembles one device graph and emits v2 epoch and audio frames", async () => {
    const { input, sent, source, worklet } = fixture();

    await input.start();
    worklet.port.onmessage?.({
      data: {
        type: "audio_frame",
        inputEpoch: "input-1",
        captureMode: "prebuffer",
        pcm16: new Int16Array([1, 2]).buffer,
      },
    } as MessageEvent);
    input.release("input-1");

    expect(sent[0]).toMatchObject({
      type: "input_epoch_started",
      input_epoch: "input-1",
    });
    expect(sent[1]).toMatchObject({
      type: "input_audio_frame",
      input_epoch: "input-1",
      sequence: 0,
      start_sample: 0,
      sample_count: 2,
      capture_mode: "prebuffer",
    });
    expect(source.connect).toHaveBeenCalledTimes(2);
    expect(worklet.port.postMessage).toHaveBeenCalledWith({
      type: "release",
      input_epoch: "input-1",
    });
  });

  it("stops tracks, worklet and context without retaining an epoch", async () => {
    const { input, runtime, worklet, track, context } = fixture();
    await input.start();

    input.stop();

    expect(track.stop).toHaveBeenCalledOnce();
    expect(worklet.disconnect).toHaveBeenCalledOnce();
    expect(context.close).toHaveBeenCalledOnce();
    expect(runtime.activeInputEpoch).toBeNull();
  });
});

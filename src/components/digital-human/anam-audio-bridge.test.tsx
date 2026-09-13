import { describe, expect, it, vi } from "vitest";
import { AnamAudioBridge } from "./anam-audio-bridge";

function pcmBase64(byteLength: number): string {
  return btoa(String.fromCharCode(...new Uint8Array(byteLength)));
}

function chunk(overrides: Partial<Parameters<AnamAudioBridge["enqueue"]>[0]> = {}) {
  return {
    pcm16Base64: pcmBase64(4_800),
    sampleRateHz: 24_000,
    generation: 7,
    speechId: "speech-7",
    sequence: 1,
    isFinal: true,
    onStarted: vi.fn(),
    onEnded: vi.fn(),
    ...overrides,
  };
}

describe("AnamAudioBridge", () => {
  it("streams PCM chunks and closes the Anam sequence", () => {
    vi.useFakeTimers();
    vi.setSystemTime(1_000);
    const sendAudioChunk = vi.fn();
    const endSequence = vi.fn();
    const bridge = new AnamAudioBridge();
    bridge.connect(
      { interruptPersona: vi.fn() },
      { sendAudioChunk, endSequence },
      { volume: 1 },
    );
    const audio = chunk();

    expect(bridge.enqueue(audio)).toBe(true);
    expect(sendAudioChunk).toHaveBeenCalledWith(audio.pcm16Base64);
    expect(bridge.completeGeneration(7)).toBe(true);
    expect(endSequence).toHaveBeenCalledOnce();

    vi.advanceTimersByTime(800);
    expect(audio.onStarted).toHaveBeenCalledOnce();
    vi.advanceTimersByTime(100);
    expect(audio.onEnded).toHaveBeenCalledOnce();
    expect(bridge.isActive(7)).toBe(false);
    vi.useRealTimers();
  });

  it("falls back when the TTS sample rate does not match", () => {
    const bridge = new AnamAudioBridge();
    bridge.connect(
      { interruptPersona: vi.fn() },
      { sendAudioChunk: vi.fn(), endSequence: vi.fn() },
      { volume: 1 },
    );
    expect(bridge.enqueue(chunk({ sampleRateHz: 16_000 }))).toBe(false);
  });

  it("interrupts every active remote generation when the session resets", () => {
    const interruptPersona = vi.fn();
    const endSequence = vi.fn();
    const bridge = new AnamAudioBridge();
    bridge.connect(
      { interruptPersona },
      { sendAudioChunk: vi.fn(), endSequence },
      { volume: 1 },
    );
    bridge.enqueue(chunk({ generation: 7 }));
    bridge.enqueue(chunk({ generation: 8 }));

    bridge.reset();

    expect(interruptPersona).toHaveBeenCalledOnce();
    expect(endSequence).toHaveBeenCalledOnce();
    expect(bridge.isActive(7)).toBe(false);
    expect(bridge.isActive(8)).toBe(false);
  });

  it("interrupts the remote avatar and resets the audio sequence", () => {
    const interruptPersona = vi.fn();
    const endSequence = vi.fn();
    const bridge = new AnamAudioBridge();
    bridge.connect(
      { interruptPersona },
      { sendAudioChunk: vi.fn(), endSequence },
      { volume: 1 },
    );
    bridge.enqueue(chunk());

    bridge.cancelGeneration(7);

    expect(interruptPersona).toHaveBeenCalledOnce();
    expect(endSequence).toHaveBeenCalledOnce();
    expect(bridge.isActive(7)).toBe(false);
  });
});

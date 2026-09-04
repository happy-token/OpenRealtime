import { describe, expect, it, vi } from "vitest";
import { LiveAvatarAudioBridge } from "./liveavatar-audio-bridge";

function encoded(bytes: number[]): string {
  return btoa(String.fromCharCode(...bytes));
}

function chunk(overrides: Partial<Parameters<LiveAvatarAudioBridge["enqueue"]>[0]> = {}) {
  return {
    pcm16Base64: encoded([1, 2]),
    sampleRateHz: 24_000,
    generation: 7,
    speechId: "speech-7",
    sequence: 1,
    isFinal: false,
    onStarted: vi.fn(),
    onEnded: vi.fn(),
    ...overrides,
  };
}

describe("LiveAvatarAudioBridge", () => {
  it("buffers realtime chunks into one LiveAvatar utterance", () => {
    const repeatAudio = vi.fn(() => "event-1");
    const bridge = new LiveAvatarAudioBridge();
    bridge.connect({ repeatAudio, interrupt: vi.fn() }, { volume: 1 });
    const first = chunk();
    const final = chunk({ pcm16Base64: encoded([3, 4]), sequence: 2, isFinal: true });

    expect(bridge.enqueue(first)).toBe(true);
    expect(bridge.enqueue(final)).toBe(true);
    expect(repeatAudio).not.toHaveBeenCalled();
    expect(bridge.completeGeneration(7)).toBe(true);

    expect(repeatAudio).toHaveBeenCalledWith(encoded([1, 2, 3, 4]));
    expect(first.onStarted).toHaveBeenCalledOnce();
    expect(bridge.isActive(7)).toBe(true);
    bridge.handleAvatarSpeechEnded();
    expect(final.onEnded).toHaveBeenCalledOnce();
    expect(bridge.isActive(7)).toBe(false);
  });

  it("falls back for incompatible sample rates", () => {
    const bridge = new LiveAvatarAudioBridge();
    bridge.connect({ repeatAudio: vi.fn(() => "event"), interrupt: vi.fn() }, { volume: 1 });
    expect(bridge.enqueue(chunk({ sampleRateHz: 16_000 }))).toBe(false);
  });

  it("interrupts active avatar playback and clears its callbacks", () => {
    const interrupt = vi.fn();
    const bridge = new LiveAvatarAudioBridge();
    bridge.connect({ repeatAudio: vi.fn(() => "event"), interrupt }, { volume: 1 });
    bridge.enqueue(chunk());
    bridge.completeGeneration(7);

    bridge.cancelGeneration(7);
    bridge.handleAvatarSpeechEnded();

    expect(interrupt).toHaveBeenCalledOnce();
    expect(bridge.isActive(7)).toBe(false);
  });
});

import { describe, expect, it, vi } from "vitest";
import { PlaybackOutputController } from "./playback-output-controller";

function fixture(accepted = true) {
  const browser = { play: vi.fn(() => true), cancelGeneration: vi.fn(() => null), reset: vi.fn(), setVolume: vi.fn() };
  const avatar = { enqueue: vi.fn(() => accepted), completeGeneration: vi.fn(() => true), cancelGeneration: vi.fn(), isActive: vi.fn(() => false), reset: vi.fn(), setVolume: vi.fn() };
  return { browser, avatar, output: new PlaybackOutputController(browser, () => avatar) };
}
const chunk = { pcm16Base64: "AA==", sampleRateHz: 16000, generation: 1, speechId: "speech", sequence: 0, isFinal: false, onStarted: vi.fn(), onEnded: vi.fn() };

describe("PlaybackOutputController", () => {
  it("routes accepted avatar audio without duplicate browser playback", () => {
    const { output, browser, avatar } = fixture();
    expect(output.enqueue(chunk)).toBe(true);
    expect(avatar.enqueue).toHaveBeenCalledWith(chunk);
    expect(browser.play).not.toHaveBeenCalled();
  });
  it("falls back to browser when avatar declines audio", () => {
    const { output, browser } = fixture(false);
    expect(output.enqueue(chunk)).toBe(false);
    expect(browser.play).toHaveBeenCalledOnce();
  });
  it("stops both outputs and suppresses late chunks and asynchronous fallback", () => {
    const { output, browser, avatar } = fixture();
    output.cancelGeneration(1);
    output.enqueue(chunk);
    output.playBrowser(chunk);
    expect(output.completeGeneration(1)).toBe(false);
    expect(browser.cancelGeneration).toHaveBeenCalledWith(1);
    expect(avatar.cancelGeneration).toHaveBeenCalledWith(1);
    expect(browser.play).not.toHaveBeenCalled();
    expect(avatar.enqueue).not.toHaveBeenCalled();
    output.enqueue({ ...chunk, generation: 2 });
    expect(avatar.enqueue).toHaveBeenCalledOnce();
  });
  it("resets both outputs and synchronizes volume", () => {
    const { output, browser, avatar } = fixture();
    output.setVolume(0.4);
    output.reset();
    expect(browser.reset).toHaveBeenCalledOnce();
    expect(avatar.reset).toHaveBeenCalledOnce();
    expect(browser.setVolume).toHaveBeenCalledWith(0.4);
    expect(avatar.setVolume).toHaveBeenCalledWith(0.4);
  });
});

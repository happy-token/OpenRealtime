import { describe, expect, it, vi } from "vitest";
import { PlaybackOutputController } from "./playback-output-controller";

function fixture(accepted = true) {
  const browser = { play: vi.fn(() => true), canPlay: vi.fn(() => true),
    stopAtSentenceEnd: vi.fn(async target => ({ ...target, type: "output_stop_result" as const,
      outcome: "queue_stopped" as const, played_position_samples: 1000 })),
    stopOutput: vi.fn(target => ({ ...target, type: "output_stop_result" as const,
      outcome: "queue_stopped" as const, played_position_samples: 0 })),
    cancelGeneration: vi.fn(() => null), reset: vi.fn(), setVolume: vi.fn() };
  const avatar = { enqueue: vi.fn(() => accepted), completeGeneration: vi.fn(() => true), cancelGeneration: vi.fn(), isActive: vi.fn(() => false), reset: vi.fn(), setVolume: vi.fn() };
  return { browser, avatar, output: new PlaybackOutputController(browser, () => avatar) };
}
const chunk = { pcm16Base64: "AA==", sampleRateHz: 16000, generation: 1, speechId: "speech", sequence: 0, isFinal: false, onStarted: vi.fn(), onEnded: vi.fn() };

describe("PlaybackOutputController", () => {
  it("does not start deferred avatar output during a browser sentence wait", async () => {
    const { output, browser, avatar } = fixture();
    output.beginEpoch("epoch");
    output.enqueue(chunk);
    avatar.enqueue.mockReturnValue(false);
    output.enqueue({ ...chunk, generation: 2, speechId: "browser" });
    let finish!: (value: Awaited<ReturnType<typeof browser.stopAtSentenceEnd>>) => void;
    browser.stopAtSentenceEnd.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    const target = { output_epoch: "epoch", speech_id: "browser", generation: 2, stop_command_id: "stop" };
    const pending = output.stopAtSentenceEnd(target, { permit_id: "permit", input_id: "input", input_version: 1,
      response_id: "browser", reply_version: 1, sentence_id: "sentence", audio_start_samples: 0,
      audio_end_samples: 1000, sample_rate_hz: 16000, max_wait_ms: 1000 });
    expect(output.completeGeneration(1)).toBe(false);
    expect(output.canUpdateResponse()).toBe(false);
    expect(avatar.completeGeneration).not.toHaveBeenCalled();
    finish({ ...target, type: "output_stop_result", outcome: "queue_stopped", played_position_samples: 1000 });
    await pending;
    expect(output.canUpdateResponse()).toBe(true);
  });

  it("binds exact stop and duplicate receipts to epoch and speech, preserving a replacement", () => {
    const { output, browser } = fixture(false);
    output.beginEpoch("epoch");
    output.enqueue(chunk);
    const target = { generation: 1,
      output_epoch: "epoch", speech_id: "speech", stop_command_id: "stop-1" };
    const result = output.stopOutput(target);
    output.enqueue({ ...chunk, speechId: "replacement" });
    expect(output.stopOutput(target)).toEqual(result);
    expect(browser.cancelGeneration).not.toHaveBeenCalled();
    expect(output.canEnqueue({ generation: 1, speechId: "replacement" })).toBe(true);
    expect(output.canEnqueue({ generation: 1, speechId: "speech" })).toBe(false);
  });

  it("rejects old epochs before cancelling any renderer", () => {
    const { output, browser, avatar } = fixture();
    output.beginEpoch("current");
    output.enqueue(chunk);
    const result = output.stopOutput({ generation: 1,
      output_epoch: "old", speech_id: "speech", stop_command_id: "old-stop" });
    expect(result.outcome).toBe("stale");
    expect(browser.cancelGeneration).not.toHaveBeenCalled();
    expect(avatar.cancelGeneration).not.toHaveBeenCalled();
  });

  it("does not claim confirmation from an avatar's fire-and-forget cancellation", () => {
    const { output } = fixture();
    output.beginEpoch("epoch");
    output.enqueue(chunk);
    const result = output.stopOutput({ generation: 1,
      output_epoch: "epoch", speech_id: "speech", stop_command_id: "stop" });
    expect(result.outcome).toBe("unknown");
    expect(result.played_position_samples).toBeNull();
    expect(output.canEnqueue({ generation: 2, speechId: "new" })).toBe(false);
  });

  it("routes accepted avatar audio without duplicate browser playback", () => {
    const { output, browser, avatar } = fixture();
    expect(output.enqueue(chunk)).toBe(true);
    expect(avatar.enqueue).toHaveBeenCalledWith(chunk);
    expect(browser.play).not.toHaveBeenCalled();
  });
  it("keeps unknown avatar output blocked across epochs, completion and volume changes", () => {
    const { output, avatar } = fixture();
    output.beginEpoch("epoch");
    output.enqueue(chunk);
    output.enqueue({ ...chunk, generation: 2, speechId: "replacement" });
    expect(output.stopOutput({ generation: 1, output_epoch: "epoch",
      speech_id: "speech", stop_command_id: "stop" }).outcome).toBe("unknown");
    expect(output.completeGeneration(2)).toBe(false);
    expect(avatar.completeGeneration).not.toHaveBeenCalled();
    output.setVolume(0.7);
    expect(avatar.setVolume).toHaveBeenLastCalledWith(0);
    output.beginEpoch("new-epoch");
    expect(output.canEnqueue({ generation: 1, speechId: "new" })).toBe(false);
    expect(output.completeGeneration(1)).toBe(false);
    expect(avatar.completeGeneration).not.toHaveBeenCalled();
  });
  it("binds stale operations to their immutable target within an epoch", () => {
    const { output, browser, avatar } = fixture(false);
    output.beginEpoch("epoch");
    output.enqueue(chunk);
    const target = { generation: 2, output_epoch: "epoch",
      speech_id: "speech", stop_command_id: "stop" };
    expect(output.stopOutput(target).outcome).toBe("stale");
    expect(output.stopOutput(target).outcome).toBe("stale");
    expect(() => output.stopOutput({ ...target, generation: 1 })).toThrow("identity was reused");
    expect(browser.stopOutput).not.toHaveBeenCalled();
    expect(output.canEnqueue({ generation: 2, speechId: "new" })).toBe(false);
    expect(browser.setVolume).toHaveBeenLastCalledWith(0);
    expect(avatar.setVolume).toHaveBeenLastCalledWith(0);
  });
  it("mutes both renderers when the stop operation budget is exhausted", () => {
    const { output, browser, avatar } = fixture(false);
    output.beginEpoch("epoch");
    output.enqueue(chunk);
    for (let index = 0; index < 512; index += 1) {
      output.stopOutput({ generation: 1, output_epoch: "epoch",
        speech_id: `absent-${index}`, stop_command_id: `stop-${index}` });
    }
    expect(output.stopOutput({ generation: 1, output_epoch: "epoch",
      speech_id: "speech", stop_command_id: "overflow" }).outcome).toBe("unknown");
    expect(browser.setVolume).toHaveBeenLastCalledWith(0);
    expect(avatar.setVolume).toHaveBeenLastCalledWith(0);
    expect(output.canEnqueue({ generation: 2, speechId: "new" })).toBe(false);
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

import { describe, expect, it } from "vitest";
import { PlaybackTextTimeline } from "./playback-text";
import type { AssistantTextAlignmentFrame } from "@/lib/frames";

function cue(text: string, start: number, end: number, generation = 1): AssistantTextAlignmentFrame {
  return { type: "assistant_text_alignment", generation, speech_id: `s-${generation}`, text, audio_start_us: start, audio_end_us: end };
}

describe("PlaybackTextTimeline", () => {
  it("keeps generated text hidden until its audio starts and advances on word cues", () => {
    const timeline = new PlaybackTextTimeline();
    expect(timeline.add(cue("你好", 0, 300_000))).toBe("");
    expect(timeline.add(cue("你好世界", 300_000, 700_000))).toBe("");
    expect(timeline.advance(1, "s-1", 100_000)).toBe("你好");
    expect(timeline.advance(1, "s-1", 310_000)).toBe("你好");
    expect(timeline.advance(1, "s-1", 400_000)).toBe("你好世界");
  });
  it("catches up when provider timings arrive after the audio position", () => {
    const timeline = new PlaybackTextTimeline();
    expect(timeline.advance(1, "s-1", 500_000)).toBe("");
    expect(timeline.add(cue("第一句。", 0, 400_000))).toBe("第一句。");
  });
  it("freezes interruption at completed tokens and rejects late cues or completion", () => {
    const timeline = new PlaybackTextTimeline();
    timeline.add(cue("你好", 0, 200_000));
    timeline.add(cue("你好世界", 200_000, 500_000));
    timeline.advance(1, "s-1", 300_000);
    expect(timeline.stop(1)).toBe("你好");
    expect(timeline.add(cue("没播放的尾巴", 500_000, 900_000))).toBeNull();
    expect(timeline.finish(1, "全部生成文字")).toBeNull();
  });
  it("rejects stale response progress and settles a provider without timings only on real playback finish", () => {
    const timeline = new PlaybackTextTimeline();
    timeline.add(cue("新回复", 0, 400_000, 2));
    expect(timeline.advance(1, "s-1", 1_000_000)).toBeNull();
    expect(timeline.advance(2, "wrong-speech", 1_000_000)).toBeNull();
    expect(timeline.finish(1, "旧全文")).toBeNull();
    expect(timeline.finish(2, "新回复")).toBe("新回复");
  });
});

it("rejects an old epoch before it can advance the current generation", () => {
  const timeline = new PlaybackTextTimeline();
  timeline.beginEpoch("current");
  expect(timeline.add({ ...cue("旧字幕", 0, 100_000, 9), output_epoch: "old" })).toBeNull();
  expect(timeline.add({ ...cue("当前字幕", 0, 100_000), output_epoch: "current" })).toBe("");
  expect(timeline.advance(1, "s-1", 100_000)).toBe("当前字幕");
  timeline.beginEpoch("next");
  expect(timeline.add({ ...cue("旧字幕", 0, 100_000), output_epoch: "current" })).toBeNull();
  expect(timeline.add({ ...cue("新字幕", 0, 100_000), output_epoch: "next" })).toBe("");
});

it("clears display content without losing the acknowledged attachment on call start or private-call reuse", () => {
  const timeline = new PlaybackTextTimeline();
  timeline.beginEpoch("acknowledged");
  timeline.reset(); // clearConversationDisplay after session_ack
  expect(timeline.add({ ...cue("第一轮", 0, 100_000), output_epoch: "acknowledged" })).toBe("");
  expect(timeline.advance(1, "s-1", 100_000)).toBe("第一轮");
  timeline.reset(); // private terminate/continue on the same socket
  expect(timeline.add({ ...cue("续谈", 0, 100_000, 2), output_epoch: "acknowledged" })).toBe("");
  expect(timeline.advance(2, "s-2", 100_000)).toBe("续谈");
  expect(timeline.add({ ...cue("旧连接", 0, 100_000, 99), output_epoch: "expired" })).toBeNull();
});

it("accepts an admitted replacement speech in the same generation after a precise stop", () => {
  const timeline = new PlaybackTextTimeline();
  timeline.beginEpoch("current");
  timeline.add({ ...cue("旧句", 0, 100_000), speech_id: "old", output_epoch: "current" });
  timeline.advance(1, "old", 50_000);
  timeline.stop(1);
  expect(timeline.add({ ...cue("新句", 0, 100_000), speech_id: "new", output_epoch: "current" })).toBe("");
  expect(timeline.advance(1, "new", 50_000)).toBe("新句");
  expect(timeline.advance(1, "old", 100_000)).toBeNull();
});

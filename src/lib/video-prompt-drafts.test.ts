import { expect, it } from "vitest";
import { parseVideoPromptDrafts } from "./video-prompt-drafts";
it("preserves both language drafts including intentionally empty edits", () => {
  expect(parseVideoPromptDrafts(JSON.stringify({ "gentle-companion": { "zh-CN": "中文修改", en: "" } })))
    .toEqual({ "gentle-companion": { "zh-CN": "中文修改", en: "" } });
});
it("ignores corrupt, obsolete, or oversized browser drafts", () => {
  expect(parseVideoPromptDrafts("invalid")).toEqual({});
  expect(parseVideoPromptDrafts(JSON.stringify({ old: { en: "x" }, custom: { en: "x".repeat(5001), "zh-CN": 42 } }))).toEqual({});
});

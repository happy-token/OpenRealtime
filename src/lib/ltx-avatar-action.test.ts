import { describe, expect, it } from "vitest";
import {
  COMPANION_EMOTION_STYLES,
  composeVideoGenerationPrompt,
  VIDEO_PROMPT_STYLES,
  VIDEO_GENERATION_DEFAULT_MODEL,
  VIDEO_GENERATION_MODELS,
  videoGenerationProviderForModel,
} from "./ltx-avatar-action";

describe("LTX Avatar action options", () => {
  it("defaults to the locally reviewed 2.3 Fast model while allowing current alternatives", () => {
    expect(VIDEO_GENERATION_DEFAULT_MODEL).toBe("ltx-2-3-fast");
    expect(VIDEO_GENERATION_MODELS.map((model) => model.id)).toEqual([
      "ltx-2-3-fast",
      "ltx-2-3-pro",
      "ltx-2-5-fast",
      "ltx-2-5-pro",
      "MiniMax-H3",
      "MiniMax-H3-Max",
      "MiniMax-H3-Context-IR",
    ]);
    expect(videoGenerationProviderForModel("MiniMax-H3")).toBe("minimax");
    expect(videoGenerationProviderForModel("MiniMax-H3-Max")).toBe("minimax");
    expect(videoGenerationProviderForModel("MiniMax-H3-Context-IR")).toBe("minimax");
  });

  it("offers six distinct bilingual role motions without fixed timestamps", () => {
    expect(VIDEO_PROMPT_STYLES.map((style) => style.name)).toEqual([
      "温柔陪伴", "活泼朋友", "专业顾问", "耐心老师", "冷静学者", "自信搭档",
    ]);
    expect(new Set(VIDEO_PROMPT_STYLES.map((style) => style.prompt)).size).toBe(6);
    expect(COMPANION_EMOTION_STYLES).toBe(VIDEO_PROMPT_STYLES);
    for (const style of VIDEO_PROMPT_STYLES) {
      const english = composeVideoGenerationPrompt("video-conversation", style.id, "en");
      const chinese = composeVideoGenerationPrompt("video-conversation", style.id, "zh-CN");
      expect(english).toContain("No speaking, speech articulation, open mouth, or visible teeth");
      expect(english).toContain("No waving, pointing, thumbs-up, repeated nodding");
      expect(english).toContain("opening posture, head position, and expression");
      expect(english).toContain("Keep the head approximately level");
      expect(chinese).toContain("全程不说话");
      expect(chinese).toContain("平缓回到开头");
      expect(chinese).toContain(style.promptZh);
      expect(english).toContain(style.prompt);
      expect(english).not.toMatch(/\d+(?:\.\d+)? seconds/);
      expect(chinese).not.toMatch(/\d+(?:\.\d+)?\s*秒/);
      expect(english.length).toBeLessThanOrEqual(5_000);
      expect(chinese.length).toBeLessThanOrEqual(5_000);
    }
  });
});

import { describe, expect, it } from "vitest";
import {
  COMPANION_EMOTION_STYLES,
  composeVideoGenerationPrompt,
  LTX_PROMPT_PRESETS,
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

  it("ships reviewed closed-mouth loop prompts", () => {
    expect(LTX_PROMPT_PRESETS.map((preset) => preset.id)).toEqual([
      "video-conversation",
    ]);
    for (const preset of LTX_PROMPT_PRESETS) {
      expect(preset.prompt).toContain("lips gently closed");
      expect(preset.prompt).toContain("loop continuity");
      expect(preset.prompt.length).toBeLessThanOrEqual(5_000);
    }
  });

  it("only exposes the reviewed speech-compatible companion prompt list", () => {
    expect(VIDEO_PROMPT_STYLES.map((style) => style.id)).toEqual([
      "sweet-vitality",
      "soft-glow",
      "cool-night",
      "gentle-intellectual",
      "melancholy-empathy",
    ]);

    const prompts = Object.fromEntries(VIDEO_PROMPT_STYLES.map((style) => [
      style.id,
      composeVideoGenerationPrompt("video-conversation", style.id),
    ]));

    for (const prompt of Object.values(prompts)) {
      expect(prompt).toContain("video-call conversation");
      expect(prompt).toContain("natural resting shape");
      expect(prompt).toContain("relaxed jaw must move coherently");
      expect(prompt).toContain("phoneme or viseme transitions");
      expect(prompt).toContain("quiet room tone only");
      expect(prompt).toContain("style-specific choreography");
      expect(prompt.length).toBeLessThanOrEqual(5_000);
    }

    expect(prompts["sweet-vitality"]).not.toContain("Absolutely no head turn");
  });

  it("ships speech-compatible companion personas with distinct emotional choreography and visual metadata", () => {
    expect(COMPANION_EMOTION_STYLES.map((style) => style.id)).toEqual([
      "sweet-vitality",
      "soft-glow",
      "cool-night",
      "gentle-intellectual",
      "melancholy-empathy",
    ]);
    expect(COMPANION_EMOTION_STYLES.map((style) => style.emotion)).toEqual([
      "开心惊喜",
      "害羞依恋",
      "冷静自持",
      "共情安慰",
      "温柔忧郁",
    ]);
    expect(COMPANION_EMOTION_STYLES[0].visualReference).toContain("高马尾");
    expect(COMPANION_EMOTION_STYLES[3].visualReference).toContain("温暖书房");
    expect(COMPANION_EMOTION_STYLES[4].visualReference).toContain("雨夜窗边");

    const choreographyMarkers = [
      "buoyant speaking energy",
      "shy but connected speaking presence",
      "cool self-possessed speaking presence",
      "empathetic reassuring speaking presence",
      "private loneliness of a quiet late night",
    ];
    COMPANION_EMOTION_STYLES.forEach((style, index) => {
      const prompt = composeVideoGenerationPrompt("video-conversation", style.id);
      expect(prompt).toContain(choreographyMarkers[index]);
      expect(prompt).toContain("do not restyle");
      expect(prompt).toContain("relaxed jaw must move coherently");
      expect(prompt).toContain("no lip-sync movement");
      expect(prompt).toContain("never freeze, paste, or pixel-lock the mouth");
      expect(prompt).toContain("speech-ready base-motion plate");
      expect(style.speechCompatible).toBe(true);
      expect(prompt.length).toBeLessThanOrEqual(5_000);
    });

    const sweetPrompt = composeVideoGenerationPrompt("video-conversation", "sweet-vitality");
    expect(sweetPrompt).toContain("no nod and no downward head movement");
    expect(sweetPrompt).not.toContain("acknowledgement nods");

    const melancholyPrompt = composeVideoGenerationPrompt("video-conversation", "melancholy-empathy");
    const intellectualPrompt = composeVideoGenerationPrompt("video-conversation", "gentle-intellectual");
    for (const marker of [
      "does not look into the lens",
      "inclines laterally 4 to 6 degrees",
      "lowered off-camera gaze",
      "fragile still pause",
      "long silent exhale",
      "want to comfort, protect, and stay beside her",
    ]) {
      expect(melancholyPrompt).toContain(marker);
      expect(intellectualPrompt).not.toContain(marker);
    }
    expect(melancholyPrompt).toContain("no comforting nod");
    expect(melancholyPrompt).toContain("No direct lens gaze during the emotional action");
  });
});

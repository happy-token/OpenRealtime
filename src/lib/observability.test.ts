import { describe, expect, it } from "vitest";
import { formatDuration, formatRate, metricLabel } from "./observability";

describe("observability presentation", () => {
  it("keeps latency and missing samples visually distinct", () => {
    expect(formatDuration(null)).toBe("—");
    expect(formatDuration(321)).toBe("321ms");
    expect(formatDuration(1321)).toBe("1.32s");
    expect(formatRate(null)).toBe("—");
    expect(formatRate(0.975)).toBe("97.5%");
  });

  it("uses readable chain names without hiding unknown modules", () => {
    expect(metricLabel("tts.time_to_first_audio")).toBe("回复启动 → 首音频（含生成）");
    expect(metricLabel("asr.speech_start_to_first_text")).toBe("ASR 首包延迟");
    expect(metricLabel("asr.last_frame_to_final_text")).toBe("ASR 尾包延迟");
    expect(metricLabel("tts.first_text_to_first_audio")).toBe("TTS 首包延迟");
    expect(metricLabel("provider.custom")).toBe("provider.custom");
  });
});

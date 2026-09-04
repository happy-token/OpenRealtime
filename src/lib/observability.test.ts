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
    expect(metricLabel("tts.time_to_first_audio")).toBe("TTS 首音频");
    expect(metricLabel("provider.custom")).toBe("provider.custom");
  });
});

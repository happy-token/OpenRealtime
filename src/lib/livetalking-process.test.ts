import { describe, expect, it } from "vitest";

import { resolveWav2LipInferenceStride } from "@/lib/livetalking-process";

describe("LiveTalking process configuration", () => {
  it("uses realtime stride two by default and accepts full-quality stride one explicitly", () => {
    expect(resolveWav2LipInferenceStride({})).toBe(2);
    expect(resolveWav2LipInferenceStride({ OPENREALTIME_WAV2LIP_INFERENCE_STRIDE: "1" })).toBe(1);
    expect(resolveWav2LipInferenceStride({ OPENREALTIME_WAV2LIP_INFERENCE_STRIDE: "2" })).toBe(2);
  });

  it("rejects unsupported inference strides instead of silently degrading quality", () => {
    expect(() => resolveWav2LipInferenceStride({
      OPENREALTIME_WAV2LIP_INFERENCE_STRIDE: "3",
    })).toThrow("must be 1 or 2");
  });
});

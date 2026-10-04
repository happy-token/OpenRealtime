import { describe, expect, it } from "vitest";
import { dashboardLatencyMetrics, metricLabel, METRIC_DESCRIPTIONS, type MetricAggregate } from "./observability";
const sample = (name: string): MetricAggregate => ({ name, sample_count: 2, p50_ms: 10, p95_ms: 20, p99_ms: 20, max_ms: 20, error_count: 0, timeout_count: 0, cancelled_count: 0, degraded_count: 0 });
describe("diagnostic latency coverage", () => {
  it("keeps unmeasured core stages visible without treating historical input wait as ASR speech latency", () => {
    const rows = dashboardLatencyMetrics([sample("asr.input_to_first_text"), sample("tts.first_text_to_first_audio")]);
    expect(rows.find(row => row.name === "asr.speech_start_to_first_text")?.metric).toBeNull();
    expect(rows.find(row => row.name === "tts.first_text_to_first_audio")?.metric?.sample_count).toBe(2);
    expect(rows.filter(row => ["turn_policy.eot_classify", "semantic_interruption.classify"].includes(row.name)).map(row => row.metric)).toEqual([null, null]);
    expect(rows.find(row => row.name === "llm.request_to_first_text")?.metric).toBeNull();
    expect(METRIC_DESCRIPTIONS["asr.input_to_first_text"]).toContain("静音");
  });
  it("distinguishes orchestration, provider first packet and full stream timings", () => {
    expect(metricLabel("tts.time_to_first_audio")).not.toBe(metricLabel("tts.first_text_to_first_audio"));
    expect(metricLabel("brain.time_to_first_text")).not.toBe(metricLabel("llm.request_to_first_text"));
    expect(METRIC_DESCRIPTIONS["provider.deepseek.responses.stream"]).toContain("不是首 Token");
  });
});

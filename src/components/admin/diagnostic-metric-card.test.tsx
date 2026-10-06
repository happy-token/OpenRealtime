import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { DiagnosticMetricCard } from "./diagnostic-metric-card";

describe("numeric diagnostic metric cards", () => {
  it("uses P50 as the primary value and exposes the measurement explanation", () => {
    const html = renderToStaticMarkup(<DiagnosticMetricCard id="asr" label="ASR" description="开口到首文本" metric={{ name: "asr", sample_count: 3, p50_ms: 120, p95_ms: 230, p99_ms: 240, max_ms: 250, error_count: 0, timeout_count: 0, cancelled_count: 0, degraded_count: 0 }} />);
    expect(html).toContain("120ms");
    expect(html).toContain("230ms");
    expect(html).toContain('role="tooltip"');
    expect(html).toContain('aria-describedby="metric-help-asr"');
    expect(html).toContain("开口到首文本");
  });
  it("does not invent zero measurements or zero connection errors", () => {
    const html = renderToStaticMarkup(<DiagnosticMetricCard id="tts" label="TTS" description="首包" metric={null} />);
    expect(html).toContain("暂无耗时样本");
    expect(html).toContain("采集未接通");
    expect(html).not.toContain("0ms");
  });
});

import { formatDuration, formatRate, type MetricAggregate, type ModuleHealth } from "@/lib/observability";
import styles from "./diagnostics-workspace.module.css";

export function DiagnosticMetricCard({ id, label, description, metric, health, onFilter }: {
  id: string; label: string; description: string; metric: MetricAggregate | null;
  health?: ModuleHealth; onFilter?: () => void;
}) {
  const tooltipId = `metric-help-${id.replaceAll(".", "-")}`;
  return <article className={styles.module} tabIndex={0} aria-describedby={tooltipId}>
    <div className={styles.modulehead}><span>{label}</span><span className={styles.metricTag}>P50</span></div>
    <strong className={styles.metricValue}>{metric?.sample_count ? formatDuration(metric.p50_ms) : "—"}</strong>
    <div className={styles.metricMeta}>{metric?.sample_count ? <>P95 {formatDuration(metric.p95_ms)} <span>· {metric.sample_count} 个样本</span></> : "暂无耗时样本"}</div>
    <div className={styles.metricCounts}>{([ ["失败", health?.error_count], ["超时", health?.timeout_count], ["断连", health?.disconnect_count] ] as const).map(([label, value]) => <button key={label} type="button" disabled={value == null || value === 0} onClick={onFilter} title={value == null ? "该统计采集未接通" : `查看${label}会话`}><span>{label}</span><b data-abnormal={Boolean(value)}>{value ?? "—"}</b></button>)}</div>
    <details className={styles.metricDetails}><summary>重试与恢复</summary><p>重试 {health?.retry_count ?? "采集未接通"} · 恢复成功率 {formatRate(health?.recovery_rate ?? null)}</p></details>
    <span id={tooltipId} role="tooltip" className={styles.metricTooltip}>{description}<br />失败与超时统计以供应商调用为主，能力失败作无供应商记录时的补充；不累计耗时跨度中的重复错误。断连仅统计明确连接异常，取消不计。— 表示采集未接通。</span>
  </article>;
}

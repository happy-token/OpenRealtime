"use client";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";
import { useLanguage } from "@/components/language/language-provider";
import { dashboardLatencyMetrics, formatClock, formatDuration, formatRate, metricLabel, type DiagnosticsOverview, type SessionSummary } from "@/lib/observability";
import styles from "./diagnostics-workspace.module.css";

async function getJson<T>(url: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(url, { cache: "no-store", signal });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error ?? `HTTP ${response.status}`);
  return body;
}
export function AdminDashboard({ username, preview }: { username: string; preview?: { overview: DiagnosticsOverview; sessions: SessionSummary[] } }) {
  const { t } = useLanguage();
  const [minutes, setMinutes] = useState(1440);
  const [overview, setOverview] = useState<DiagnosticsOverview | null>(preview?.overview ?? null);
  const [sessions, setSessions] = useState<SessionSummary[]>(preview?.sessions ?? []);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [deleting, setDeleting] = useState(false);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(!preview);
  const [health, setHealth] = useState<import("@/lib/observability").CollectionHealth | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const refresh = useCallback(() => setRevision(value => value + 1), []);
  useEffect(() => {
    if (preview) return;
    const controller = new AbortController();
    setBusy(true); setErrors([]); setSelectedIds([]); setOverview(null); setSessions([]);
    void Promise.allSettled([
      getJson<DiagnosticsOverview>(`/api/observability/overview?minutes=${minutes}`, controller.signal),
      getJson<SessionSummary[]>(`/api/observability/sessions?minutes=${minutes}&limit=500`, controller.signal),
      getJson<import("@/lib/observability").CollectionHealth>("/api/observability/health", controller.signal),
    ]).then(([aggregate, list, collection]) => {
      if (controller.signal.aborted) return;
      const failures: string[] = [];
      if (aggregate.status === "fulfilled") setOverview(aggregate.value); else failures.push("总览指标暂时不可用");
      if (list.status === "fulfilled") setSessions(list.value); else failures.push("会话列表暂时不可用");
      setHealth(collection.status === "fulfilled" && collection.value?.telemetry && collection.value?.debug_log ? collection.value : null);
      setErrors(failures); setBusy(false);
    });
    return () => controller.abort();
  }, [minutes, revision, preview]);
  const deleteSelected = async () => {
    if (preview || !selectedIds.length || deleting) return;
    if (!window.confirm(`永久删除这 ${selectedIds.length} 个会话的诊断记录？此操作无法撤销。`)) return;
    setDeleting(true);
    try {
      const response = await fetch("/api/observability/sessions", { method: "DELETE", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_ids: selectedIds }) });
      if (!response.ok) throw new Error("删除失败");
      setSelectedIds([]); refresh();
    } catch { setErrors(previous => [...previous, "删除失败，请稍后重试"]); }
    finally { setDeleting(false); }
  };
  const filtered = useMemo(() => sessions.filter(session => session.voice_session_id.toLowerCase().includes(query.trim().toLowerCase()) && (status === "all" || (session.error_count + session.timeout_count + session.no_response_count > 0) === (status === "abnormal"))), [sessions, query, status]);
  const metric = (name: string) => overview?.metrics.find(value => value.name === name);
  const response = metric("turn.speech_end_to_client_playback");
  const responseProxy = metric("turn.endpoint_to_client_playback");
  const stop = metric("barge_in.speech_start_to_client_stop");
  const stopProxy = metric("barge_in.time_to_client_stop");
  const histogram = Array.from({ length: 12 }, (_, index) => {
    const end = Date.now(), width = minutes * 60_000 / 12;
    return sessions.filter(session => { const at = Date.parse(session.first_event_at); return at >= end - width * (12 - index) && at < end - width * (11 - index); }).length;
  });
  return <WorkspaceShell><div className={styles.page}>
    {preview ? <p className={styles.muted}>主题预览 · 示例数据 · 复用真实后台组件</p> : null}
    <header className={styles.heading}><div><h1>{t("运行总览")}</h1><div className={styles.muted}>{t("数据日志后台")} · {username}</div></div><button onClick={refresh} disabled={busy || Boolean(preview)} aria-label={t("刷新数据")}><RefreshCw size={16} /></button></header>
    <div className={styles.toolbar}><input className={styles.search} value={query} onChange={event => setQuery(event.target.value)} aria-label={t("搜索 Session ID")} placeholder={t("搜索 Session ID")} /><select disabled={Boolean(preview)} aria-label={t("观察窗口")} value={minutes} onChange={event => setMinutes(Number(event.target.value))}><option value={60}>1 小时</option><option value={1440}>24 小时</option><option value={10080}>7 天</option></select><select aria-label={t("状态筛选")} value={status} onChange={event => setStatus(event.target.value)}><option value="all">全部状态</option><option value="abnormal">异常</option><option value="normal">正常</option></select>{/^[A-Za-z0-9._:-]{1,128}$/.test(query.trim()) ? <Link className={styles.button} href={preview ? `/demos/diagnostics?session=${encodeURIComponent(query.trim())}` : `/admin/sessions/${encodeURIComponent(query.trim())}`}>{t("按 ID 查看详情")}</Link> : null}</div>
    {busy ? <p className={styles.busy}>{t("正在读取诊断数据…")}</p> : null}
    {errors.map(error => <div role="alert" className={styles.error} key={error}>{t(error)}</div>)}
    <div className={styles.kpis}><Kpi title={t("会话量")} value={String(overview?.session_count ?? "—")} hint={t("当前时间窗口，全局统计")} /><Kpi title={t("有效回复成功率")} value={formatRate(overview?.success_rate ?? null)} hint={`${overview?.successful_turn_count ?? "—"} / ${overview ? overview.turn_count - overview.interrupted_count : "—"}`} /><Kpi title={t("用户停说 → 客户端首播")} value={formatDuration(response?.p95_ms ?? null)} hint={response ? `P95 · n=${response.sample_count}` : `未采集；端点到播放回执 P95 ${formatDuration(responseProxy?.p95_ms ?? null)}`} /><Kpi title={t("有效打断开口 → 旧输出停播")} value={formatDuration(stop?.p95_ms ?? null)} hint={stop ? `P95 · n=${stop.sample_count}` : `未采集；确认到停播回执 P95 ${formatDuration(stopProxy?.p95_ms ?? null)}`} /></div>
    <section className={styles.panel}><div className={styles.panelhead}><h2>{t("会话活动趋势")}</h2><span className={styles.muted}>{t("当前窗口内的会话开始数")}</span></div><div className={styles.trend} role="img" aria-label={t("会话开始数分布")}>{histogram.map((count, index) => <div key={index} title={`区间 ${index + 1}: ${count} 个会话`} style={{ height: `${count / Math.max(1, ...histogram) * 100}%` }} />)}</div><div className={styles.note}>{sessions.length >= 500 ? "列表已达 500 条上限，活动趋势可能不完整。" : "趋势基于已加载会话；指标卡统计范围由观察窗口决定，Session ID 与状态筛选仅作用于列表。"}</div></section>
    {!preview && !busy && health?.status !== "ok" ? <p className={styles.error} role="status">{health ? `日志采集异常：遥测丢弃 ${health.telemetry.dropped_events} 条，决策日志丢弃 ${health.debug_log.dropped_events} 条；写入失败 ${health.telemetry.write_error || health.debug_log.write_error ? "是" : "否"}。这是进程级统计，会话日志完整性需核查。` : "采集健康状态不可用，无法确认日志完整性。"}</p> : null}
    <section className={styles.panel}><div className={styles.panelhead}><h2>{t("模块响应延迟")}</h2><span className={styles.muted}>P50 / P95 / P99</span></div><div className={styles.note}>分位数基于当前窗口内全部已计时尝试（包括失败与取消），不是仅成功请求；未采集阶段不显示为零。</div><div className={styles.modules}>{dashboardLatencyMetrics(overview?.metrics ?? []).map(({ name, metric: value, description }) => <article className={styles.module} key={name}><div className={styles.modulehead}><span title={name}>{metricLabel(name)}</span><strong>{value?.sample_count ? formatDuration(value.p95_ms) : "未采集"}</strong></div>{value?.sample_count ? <><div className={styles.bar}><i style={{ width: `${Math.min(100, value.p95_ms / Math.max(1, ...(overview?.metrics ?? []).map(item => item.p95_ms)) * 100)}%` }} /></div><small className={styles.muted}>P50 {formatDuration(value.p50_ms)} · P95 {formatDuration(value.p95_ms)} · P99 {formatDuration(value.p99_ms)} · n={value.sample_count}<br />计时样本错误 {value.error_count} · 超时 {value.timeout_count} · 取消 {value.cancelled_count}</small></> : <p className={styles.muted}>当前窗口无耗时样本；不代表零延迟。</p>}<p className={styles.metricdescription}>{description}</p></article>)}</div></section>
    <section className={styles.panel}><h2>模块失败事件</h2><p className={styles.muted}>包含未产生耗时样本的能力失败；事件数不等于失败请求数。</p>{overview?.capability_failures ? overview.capability_failures.length ? overview.capability_failures.map(item => <p key={item.capability}>{item.capability}：错误 {item.error_count} · 超时 {item.timeout_count}</p>) : <p>当前窗口未记录能力失败事件。</p> : <p>该统计尚不可用。</p>}</section>
    <section className={styles.panel}><div className={styles.panelhead}><h2>{t("会话日志")}</h2><button disabled={Boolean(preview) || !selectedIds.length || deleting || busy} onClick={deleteSelected}>{deleting ? "正在删除…" : `删除选中 (${selectedIds.length})`}</button><span className={styles.muted}>{filtered.length} / {sessions.length}</span></div><div className={styles.tablewrap}><table><thead><tr><th>选择</th><th>开始时间</th><th>Session ID</th><th>时长</th><th>轮次</th><th>状态</th><th>错误 / 超时</th><th>事件</th><th>操作</th></tr></thead><tbody>{filtered.map(session => <tr key={session.voice_session_id}><td><input type="checkbox" disabled={Boolean(preview) || deleting || busy} aria-label={`选择会话 ${session.voice_session_id}`} checked={selectedIds.includes(session.voice_session_id)} onChange={event => setSelectedIds(previous => event.target.checked ? [...previous, session.voice_session_id].slice(0, 100) : previous.filter(id => id !== session.voice_session_id))} /></td><td>{formatClock(session.first_event_at)}</td><td>{session.voice_session_id}</td><td>{formatDuration(Date.parse(session.last_event_at) - Date.parse(session.first_event_at))}</td><td>{session.turn_count}</td><td>{session.error_count + session.timeout_count + session.no_response_count ? "需关注" : "未发现异常"}</td><td>{session.error_count} / {session.timeout_count}</td><td>{session.event_count}</td><td><Link className={styles.button} aria-label={`查看会话 ${session.voice_session_id}`} href={preview ? `/demos/diagnostics?session=${encodeURIComponent(session.voice_session_id)}` : `/admin/sessions/${encodeURIComponent(session.voice_session_id)}`}>{t("查看详情")} →</Link></td></tr>)}</tbody></table></div>{!busy && !filtered.length ? <p className={styles.empty}>{t("没有匹配会话。可直接输入 Session ID 查询历史详情。")}</p> : null}<div className={styles.note}>{t("用量和费用作为辅助信息，待采集后展示。")}</div></section>
  </div></WorkspaceShell>;
}
function Kpi({ title, value, hint }: { title: string; value: string; hint: string }) { return <article className={styles.kpi}><small>{title}</small><strong>{value}</strong><small>{hint}</small></article>; }

"use client";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";
import { useLanguage } from "@/components/language/language-provider";
import { dashboardLatencyMetrics, diagnosticModule, formatClock, formatDuration, formatRate, loadDiagnosticsOverview, metricLabel, type DiagnosticsOverview, type SessionSummary } from "@/lib/observability";
import styles from "./diagnostics-workspace.module.css";
import { DiagnosticMetricCard } from "./diagnostic-metric-card";

export function AdminDashboard({ username, preview }: { username: string; preview?: { overview: DiagnosticsOverview; sessions: SessionSummary[] } }) {
  const { t } = useLanguage();
  const [minutes, setMinutes] = useState(1440);
  const [overview, setOverview] = useState<DiagnosticsOverview | null>(preview?.overview ?? null);
  const [sessions, setSessions] = useState<SessionSummary[]>(preview?.sessions ?? []);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [moduleFilter, setModuleFilter] = useState("all");
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
    void loadDiagnosticsOverview(minutes, controller.signal).then(result => {
      if (controller.signal.aborted) return;
      setOverview(result.overview); setSessions(result.sessions); setHealth(result.health);
      setErrors(result.errors); setBusy(false);
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
  const filtered = useMemo(() => sessions.filter(session => session.voice_session_id.toLowerCase().includes(query.trim().toLowerCase()) && (status === "all" || (session.error_count + session.timeout_count + session.no_response_count + (session.disconnect_count ?? 0) > 0) === (status === "abnormal")) && (moduleFilter === "all" || session.failure_names?.some(name => diagnosticModule(name) === moduleFilter))), [sessions, query, status, moduleFilter]);
  const metric = (name: string) => overview?.metrics.find(value => value.name === name);
  const response = metric("turn.speech_end_to_client_playback");
  const transportHealth = overview?.module_health?.find(value => value.module === "transport");
  const stop = metric("barge_in.speech_start_to_client_stop");

  return <WorkspaceShell><div className={styles.page}>
    {preview ? <p className={styles.muted}>主题预览 · 示例数据 · 复用真实后台组件</p> : null}
    <header className={styles.heading}><div><h1>{t("会话诊断")}</h1><div className={styles.muted}>{t("运行总览")} · {username}</div></div><button onClick={refresh} disabled={busy || Boolean(preview)} aria-label={t("刷新数据")}><RefreshCw size={16} /></button></header>
    <div className={styles.toolbar}><input className={styles.search} value={query} onChange={event => setQuery(event.target.value)} aria-label={t("搜索 Session ID")} placeholder={t("搜索 Session ID")} /><select disabled={Boolean(preview)} aria-label={t("观察窗口")} value={minutes} onChange={event => setMinutes(Number(event.target.value))}><option value={60}>1 小时</option><option value={1440}>24 小时</option><option value={10080}>7 天</option></select><select aria-label={t("状态筛选")} value={status} onChange={event => setStatus(event.target.value)}><option value="all">全部状态</option><option value="abnormal">异常</option><option value="normal">正常</option></select><select aria-label="模块异常筛选" value={moduleFilter} onChange={event => setModuleFilter(event.target.value)}><option value="all">全部模块</option>{Object.entries({asr:"ASR",eot:"语义判停",interruption:"语义打断",llm:"LLM",tts:"TTS",playback:"客户端播放",transport:"连接"}).map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select>{/^[A-Za-z0-9._:-]{1,128}$/.test(query.trim()) ? <Link className={styles.button} href={preview ? `/demos/diagnostics?session=${encodeURIComponent(query.trim())}` : `/settings/session-diagnostics/sessions/${encodeURIComponent(query.trim())}`}>{t("按 ID 查看详情")}</Link> : null}</div>
    {busy ? <p className={styles.busy}>{t("正在读取诊断数据…")}</p> : null}
    {errors.map(error => <div role="alert" className={styles.error} key={error}>{t(error)}</div>)}
    <div className={styles.kpis}>
      <Kpi title={t("响应延迟")} value={formatDuration(response?.p50_ms ?? null)} hint={response ? `P95 ${formatDuration(response.p95_ms)} · ${response.sample_count} 个样本 · VAD 估算` : overview?.latency_collection_ready ? "暂无有效样本" : "采集未接通 / 尚无新版本会话"} description="用户停说（VAD 估算）到客户端首播回执，包含检测误差和回传耗时；历史会话不补造样本。" />
      <Kpi title={t("打断延迟")} value={formatDuration(stop?.p50_ms ?? null)} hint={stop ? `P95 ${formatDuration(stop.p95_ms)} · ${stop.sample_count} 个样本 · VAD 估算` : overview?.latency_collection_ready ? "暂无有效打断样本" : "采集未接通 / 尚无新版本会话"} description="有效抢话的开口检测到对应旧输出停播回执；附和、主动挂断和自然播放结束不计。" />
      <Kpi title="失败轮次" value={String(overview?.failed_turn_count ?? "—")} hint={overview ? `已记录终态 ${overview.turn_count} 轮 · 无响应 ${overview.no_response_count}` : "正在读取"} description="按 Session 与 Response ID 去重的失败、超时、无响应终态，不含正常打断取消；无播放回执不能直接归为成功。" />
      <Kpi title="异常断连" value={String(transportHealth?.disconnect_count ?? "—")} hint={transportHealth?.disconnect_count == null ? "采集未接通 / 无新版本会话" : `影响 ${transportHealth.affected_session_count ?? 0} 个会话`} description="活动会话进入重连状态的次数；相同断连的重复通知只计一次。" />
      <Kpi title="恢复成功率" value={formatRate(transportHealth?.recovery_rate ?? null)} hint={transportHealth?.disconnect_count == null ? "采集未接通" : `恢复 ${transportHealth.recovered_count ?? 0} · 失败 ${transportHealth.recovery_failed_count ?? 0}`} description="异常断连后重新进入可交互状态占已结束恢复尝试的比例；进行中不记为失败。" />
    </div>

    {!preview && !busy && health?.status !== "ok" ? <p className={styles.error} role="status">{health ? `日志采集异常：遥测丢弃 ${health.telemetry.dropped_events} 条，决策日志丢弃 ${health.debug_log.dropped_events} 条；写入失败 ${health.telemetry.write_error || health.debug_log.write_error ? "是" : "否"}。这是进程级统计，会话日志完整性需核查。` : "采集健康状态不可用，无法确认日志完整性。"}</p> : null}
    <section className={styles.panel}><div className={styles.panelhead}><h2>{t("模块响应延迟")}</h2><span className={styles.muted}>P50 · 毫秒 / 秒</span></div><div className={styles.modules}>{dashboardLatencyMetrics(overview?.metrics ?? []).filter(value => ["jev.eot.slot_wait", "jev.eot.client_ready", "jev.eot.request", "provider.asr.connection_setup", "provider.tts.connection_setup", "asr.speech_start_to_first_text", "asr.last_frame_to_final_text", "turn_policy.eot_classify", "semantic_interruption.classify", "llm.request_to_first_text", "tts.first_text_to_first_audio"].includes(value.name)).map(({ name, metric: value, description }) => <DiagnosticMetricCard key={name} id={name} label={metricLabel(name)} description={description} metric={value} health={overview?.module_health?.find(item => item.module === ((name.startsWith("asr.") || name.startsWith("provider.asr.")) ? "asr" : name.startsWith("llm.") ? "llm" : (name.startsWith("tts.") || name.startsWith("provider.tts.")) ? "tts" : name.startsWith("semantic_") ? "interruption" : "eot"))} onFilter={() => { setStatus("abnormal"); setModuleFilter(diagnosticModule(name) ?? "all"); }} />)}<DiagnosticMetricCard id="playback" label="客户端播放" description="客户端报告的音频欠载耗时；缺少播放回执不能认定为零延迟或播放成功。" metric={metric("client.playback_underrun") ?? null} health={overview?.module_health?.find(item => item.module === "playback")} onFilter={() => { setStatus("abnormal"); setModuleFilter("playback"); }} /><DiagnosticMetricCard id="transport" label="连接恢复" description="意外断连到恢复可交互状态的耗时；主动挂断不计入。" metric={metric("transport.recovered") ?? null} health={transportHealth} onFilter={() => { setStatus("abnormal"); setModuleFilter("transport"); }} /></div><div className={styles.note}>悬停或聚焦卡片查看测量说明。失败与超时为调用事件统计；— 表示采集未接通，暂无样本不等于零延迟。</div></section>
    <section className={styles.panel}><h2>模块失败事件</h2><p className={styles.muted}>包含未产生耗时样本的能力失败；事件数不等于失败请求数。</p>{overview?.capability_failures ? overview.capability_failures.length ? overview.capability_failures.map(item => <p key={item.capability}>{item.capability}：错误 {item.error_count} · 超时 {item.timeout_count}</p>) : <p>当前窗口未记录能力失败事件。</p> : <p>该统计尚不可用。</p>}</section>
    <section className={styles.panel}><div className={styles.panelhead}><h2>{t("会话日志")}</h2><button disabled={Boolean(preview) || !selectedIds.length || deleting || busy} onClick={deleteSelected}>{deleting ? "正在删除…" : `删除选中 (${selectedIds.length})`}</button><span className={styles.muted}>{filtered.length} / {sessions.length}</span></div><div className={styles.tablewrap}><table><thead><tr><th>选择</th><th>开始时间</th><th>Session ID</th><th>时长</th><th>轮次</th><th>状态</th><th>错误 / 超时</th><th>事件</th><th>操作</th></tr></thead><tbody>{filtered.map(session => <tr key={session.voice_session_id}><td><input type="checkbox" disabled={Boolean(preview) || deleting || busy} aria-label={`选择会话 ${session.voice_session_id}`} checked={selectedIds.includes(session.voice_session_id)} onChange={event => setSelectedIds(previous => event.target.checked ? [...previous, session.voice_session_id].slice(0, 100) : previous.filter(id => id !== session.voice_session_id))} /></td><td>{formatClock(session.first_event_at)}</td><td>{session.voice_session_id}</td><td>{formatDuration(Date.parse(session.last_event_at) - Date.parse(session.first_event_at))}</td><td>{session.turn_count}</td><td>{session.error_count + session.timeout_count + session.no_response_count + (session.disconnect_count ?? 0) ? "需关注" : "未发现异常"}</td><td>{session.error_count} / {session.timeout_count}</td><td>{session.event_count}</td><td><Link className={styles.button} aria-label={`查看会话 ${session.voice_session_id}`} href={preview ? `/demos/diagnostics?session=${encodeURIComponent(session.voice_session_id)}` : `/settings/session-diagnostics/sessions/${encodeURIComponent(session.voice_session_id)}`}>{t("查看详情")} →</Link></td></tr>)}</tbody></table></div>{!busy && !filtered.length ? <p className={styles.empty}>{t("没有匹配会话。可直接输入 Session ID 查询历史详情。")}</p> : null}<div className={styles.note}>{t("用量和费用作为辅助信息，待采集后展示。")}</div></section>
  </div></WorkspaceShell>;
}
function Kpi({ title, value, hint, description }: { title: string; value: string; hint: string; description?: string }) { return <article className={styles.kpi} tabIndex={0} title={description}><small>{title}</small><strong>{value}</strong><small>{hint}</small></article>; }

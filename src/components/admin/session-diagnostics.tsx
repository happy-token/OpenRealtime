"use client";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";
import { useLanguage } from "@/components/language/language-provider";
import { buildReplayTurns } from "@/lib/admin-diagnostics";
import { METRIC_DESCRIPTIONS, formatClock, formatDuration, metricLabel } from "@/lib/observability";
import { exactDuration, interruptionEvents, measuredSpans, type SessionDiagnosticsReport } from "@/lib/session-diagnostics-report";
import styles from "./diagnostics-workspace.module.css";

export function SessionDiagnostics({ sessionId, preview }: { sessionId: string; preview?: SessionDiagnosticsReport }) {
  const { t } = useLanguage();
  const [report, setReport] = useState<SessionDiagnosticsReport | null>(preview ?? null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(!preview);
  const [generation, setGeneration] = useState<number | null>(null);
  const [tab, setTab] = useState("chain");
  const [selectedEvent, setSelectedEvent] = useState<string | null>(null);
  const [paging, setPaging] = useState(false);
  const loadMore = async () => {
    if (!report || paging) return;
    const params = new URLSearchParams();
    if (report.telemetry?.next_cursor) params.set("telemetry_cursor", report.telemetry.next_cursor);
    if (report.debug_log?.next_cursor) params.set("debug_cursor", report.debug_log.next_cursor);
    if (!params.size) return;
    setPaging(true); setError("");
    try {
      const response = await fetch(`/api/observability/sessions/${encodeURIComponent(sessionId)}/diagnostics?${params}`, { cache: "no-store", signal: AbortSignal.timeout(15_000) });
      const next: SessionDiagnosticsReport = await response.json();
      if (!response.ok || (params.has("telemetry_cursor") && !next.telemetry) || (params.has("debug_cursor") && !next.debug_log)) throw new Error("日志续页读取失败，请重试");
      setReport(previous => {
        if (!previous || previous.session_id !== next.session_id) return previous;
        const merge = <T extends { event_id: string },>(before: T[], after: T[]) => [...new Map([...before, ...after].map(item => [item.event_id, item])).values()];
        return { ...previous, collection_health: next.collection_health, sources: { ...previous.sources, ...(params.has("telemetry_cursor") ? { telemetry: next.sources.telemetry } : {}), ...(params.has("debug_cursor") ? { debug_log: next.sources.debug_log } : {}) }, telemetry: params.has("telemetry_cursor") && next.telemetry ? { ...next.telemetry, events: merge(previous.telemetry?.events ?? [], next.telemetry.events) } : previous.telemetry, debug_log: params.has("debug_cursor") && next.debug_log ? { ...next.debug_log, entries: merge(previous.debug_log?.entries ?? [], next.debug_log.entries) } : previous.debug_log };
      });
    } catch (cause) { setError(cause instanceof Error ? cause.message : "日志续页读取失败"); } finally { setPaging(false); }
  };
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (preview) return;
    const controller = new AbortController(); setLoading(true); setReport(null); setError(""); setGeneration(null); setSelectedEvent(null);
    void fetch(`/api/observability/sessions/${encodeURIComponent(sessionId)}/diagnostics`, { cache: "no-store", signal: controller.signal }).then(async response => {
      const data = await response.json();
      if (!response.ok) throw new Error(data.error ?? (response.status === 404 ? "未找到该会话" : "诊断数据暂时不可用"));
      if (!controller.signal.aborted) setReport(data);
    }).catch(cause => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "诊断读取失败"); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [sessionId, revision, preview]);
  const turns = useMemo(() => {
    if (!report) return [];
    const existing = report.telemetry ? buildReplayTurns(report.telemetry, report.conversation) : [];
    const ids = new Set([...existing.map(turn => turn.generation), ...report.conversation.map(item => item.generation), ...(report.debug_log?.entries.flatMap(entry => entry.generation === null ? [] : [entry.generation]) ?? [])]);
    return [...ids].sort((a, b) => a - b).map(id => ({ generation: id, messages: report.conversation.filter(item => item.generation === id), events: report.telemetry?.events.filter(event => event.generation === id) ?? [] }));
  }, [report]);
  const selected = turns.find(turn => turn.generation === generation) ?? turns[0];
  const spans = measuredSpans(selected?.events ?? []);
  const extent = Math.max(1, ...spans.map(span => span.start + span.duration));
  const event = selected?.events.find(item => item.event_id === selectedEvent);
  const logs = report?.debug_log?.entries.filter(entry => selected ? entry.generation === selected.generation || entry.generation === null : true) ?? [];
  const unassociatedEvents = report?.telemetry?.events.filter(item => item.generation === null) ?? [];
  const interruptions = interruptionEvents(selected?.events ?? []);
  const exportReport = () => {
    if (!report) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }));
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = `${sessionId}-diagnostics.json`; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return <WorkspaceShell><div className={styles.page}>
    {preview ? <p className={styles.muted}>主题预览 · 示例数据 · 复用真实后台组件</p> : null}
    <Link className={styles.button} href={preview ? "/demos/diagnostics" : "/settings/session-diagnostics"}>← {t("返回运行总览")}</Link>
    <header className={styles.heading} style={{ marginTop: 20 }}><div><h1>{t("会话详情")}</h1><span className={styles.muted}>{sessionId}</span></div><div className={styles.toolbar} style={{ margin: 0 }}><button onClick={() => setRevision(value => value + 1)} disabled={loading || Boolean(preview)}>{t("刷新")}</button><button onClick={exportReport} disabled={!report}>{t("导出诊断 JSON")}</button></div></header>
    {loading ? <p className={styles.busy}>{t("正在读取会话数据…")}</p> : null}
    {error ? <p role="alert" className={styles.error}>{t(error)}</p> : null}
    {report ? <>
      <div className={styles.metadata}><span>{turns.length} {t("轮对话")}</span><span>{t("开始时间")} {formatClock(report.telemetry?.summary.first_event_at ?? "")}</span><span>{t("事件")} {report.telemetry?.events.length ?? "—"}</span><span>{t("决策日志")} {report.debug_log?.entries.length ?? "—"}</span></div>
      {!preview && report.collection_health?.status !== "ok" ? <div className={styles.error} role="status">{report.collection_health ? "日志采集存在丢弃或写入异常，当前会话记录可能不完整。" : "采集健康状态不可用，无法确认日志完整性。"}</div> : null}
      {Object.entries(report.sources).filter(([, source]) => source.status !== "available" || source.truncated).map(([name, source]) => <div className={styles.error} role="status" key={name}>{name}: {source.status !== "available" ? t("没有记录或数据源不可用") : t("已达到查询上限，当前内容可能不完整")}</div>)}
      {!preview && (report.telemetry?.next_cursor || report.debug_log?.next_cursor) ? <button className={styles.button} disabled={paging} onClick={loadMore}>{paging ? "正在加载…" : "加载更多日志"}</button> : null}
      <div className={styles.detailgrid}><section className={styles.panel}><div className={styles.panelhead}><h2>{t("对话与音频")}</h2><span className={styles.muted}>{turns.length} turns</span></div><div className={styles.audio}>{t("双向音频尚未接入录制存储，当前无法回放。")}<br />{t("已确认的录音策略：所有会话默认录音，保留 7 天，标记会话可长期保留。该策略尚未启用。")}</div><div className={styles.turnlist}>{turns.map(turn => <button className={styles.turn} key={turn.generation} aria-pressed={selected?.generation === turn.generation} onClick={() => { setGeneration(turn.generation); setSelectedEvent(null); }}><small>{t("轮次")} {turn.generation} · {turn.events.length} {t("事件")}</small>{turn.messages.map(message => <p key={message.item_id}><small>{message.role === "user" ? t("用户") : t("助手")}</small><br />{message.text}</p>)}{!turn.messages.length ? <p>{t("该轮没有已提交的对话文本。")}</p> : null}</button>)}{!turns.length ? <p className={styles.empty}>{t("没有可关联的轮次。")}</p> : null}</div></section>
        <div><section className={styles.panel}><div className={styles.panelhead}><h2>{selected ? `${t("轮次")} ${selected.generation} · ${t("诊断详情")}` : t("会话事件")}</h2><span className={styles.muted}>{selected?.events.length ?? 0} {t("事件")}</span></div><div className={styles.tabs} role="tablist" aria-label={t("诊断视图")}>{[["chain", "模块链路"], ["stop", "打断过程"], ["logs", "原始日志"]].map(([id, label]) => <button key={id} id={`tab-${id}`} role="tab" aria-selected={tab === id} aria-controls={`panel-${id}`} onClick={() => setTab(id)}>{t(label)}</button>)}</div>
          <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
          {tab === "chain" ? <div className={styles.spans}><div className={styles.muted}>{t("根据真实事件结束时间和已记录 duration 重建；起点为本轮最早可测阶段。")}</div><div className={styles.axis}><span>0</span><span>{formatDuration(extent / 2)}</span><span>{formatDuration(extent)}</span></div>{spans.map(span => <div className={styles.spanrow} key={span.event.event_id}><span>{metricLabel(span.event.name)}<br /><small>{formatDuration(span.duration)}</small></span><div className={styles.track}><button className={styles.spanbar} aria-label={`${t("查看")} ${span.event.name}`} title={`${span.start.toFixed(1)}–${(span.start + span.duration).toFixed(1)} ms`} onClick={() => setSelectedEvent(span.event.event_id)} style={{ left: `${span.start / extent * 100}%`, width: `${Math.min(100 - span.start / extent * 100, span.duration / extent * 100)}%` }} /></div></div>)}{!spans.length ? <p className={styles.empty}>{t("该轮尚无可测量的模块耗时。")}</p> : null}{event ? <div className={styles.selected}><strong>{metricLabel(event.name)}</strong><p>{METRIC_DESCRIPTIONS[event.name] ?? event.name}</p><p>{formatDuration(event.duration_ms)} · {event.outcome} · {event.event_id}</p><pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(event.attributes, null, 2)}</pre></div> : null}<div className={styles.note}>{t("并行阶段不相加作为整体延迟。缺失指标不会以近似指标替代。")}</div></div> : null}
          {tab === "stop" ? <><div className={styles.spans}><div className={styles.kpis}><div className={styles.kpi}><small>{t("有效开口 → 客户端停播")}</small><strong>{formatDuration(exactDuration(selected?.events ?? [], "barge_in.speech_start_to_client_stop"))}</strong></div><div className={styles.kpi}><small>{t("确认打断 → 停播回执（代理值）")}</small><strong>{formatDuration(exactDuration(selected?.events ?? [], "barge_in.time_to_client_stop"))}</strong></div>{["playback.stop_request_to_receipt", "playback.stop_receipt_to_handoff", "playback.stop_request_to_handoff"].map(name => <div className={styles.kpi} key={name} title={METRIC_DESCRIPTIONS[name]}><small>{metricLabel(name)}</small><strong>{formatDuration(exactDuration(selected?.events ?? [], name))}</strong></div>)}</div><p className={styles.note}>{t("停播回执仅证明本地音频队列已停止。未知、超时和取消单独记录，不能作为成功耗时；交接总等待与子阶段不重复相加。")}</p></div>{interruptions.map(item => <div className={styles.event} key={item.event_id}><strong>{metricLabel(item.name)}</strong><small>{formatClock(item.occurred_at)} · {formatDuration(item.duration_ms)} · {item.outcome}</small><details><summary>{t("查看事件")}</summary><pre>{JSON.stringify(item, null, 2)}</pre></details></div>)}{!interruptions.length ? <p className={styles.empty}>{t("该轮没有记录到打断事件；不能据此判定没有发生打断。")}</p> : null}</> : null}
          {tab === "logs" ? <><div className={styles.note}>{t("决策日志与运行事件分别保留原始标识和采集时间。")}</div>{logs.map(entry => <div className={styles.event} key={entry.event_id}><strong>{entry.stage} · {entry.event}</strong><p>{entry.summary}</p><small>{formatClock(entry.occurred_at)} · {entry.event_id}</small><details><summary>{t("查看详情")}</summary><pre>{JSON.stringify(entry.detail, null, 2)}</pre></details></div>)}{(selected?.events ?? report.telemetry?.events ?? []).map(item => <div className={styles.event} key={item.event_id}><strong>{metricLabel(item.name)}</strong><small>{formatClock(item.occurred_at)} · {item.outcome} · {formatDuration(item.duration_ms)}</small>{item.error_message ? <p>{item.error_message}</p> : null}<details><summary>{t("查看原始事件")}</summary><pre>{JSON.stringify(item, null, 2)}</pre></details></div>)}</> : null}
          </div></section>{unassociatedEvents.length ? <section className={styles.panel}><div className={styles.panelhead}><h2>{t("未关联轮次事件")}</h2><span>{unassociatedEvents.length}</span></div>{unassociatedEvents.map(item => <div className={styles.event} key={item.event_id}><strong>{metricLabel(item.name)}</strong><small>{formatClock(item.occurred_at)} · {item.outcome} · {formatDuration(item.duration_ms)}</small><details><summary>{t("查看原始事件")}</summary><pre>{JSON.stringify(item, null, 2)}</pre></details></div>)}</section> : null}<section className={styles.panel}><div className={styles.panelhead}><h2>{t("交给 Agent 排查")}</h2></div><div className={styles.note}><code>GET /api/observability/sessions/{sessionId}/diagnostics</code><p>{t("统一返回对话、模块指标、决策日志及数据源完整度。当前使用应用管理员会话认证。")}</p></div></section></div>
      </div>
    </> : null}
  </div></WorkspaceShell>;
}

"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  Activity,
  ArrowUpRight,
  AudioLines,
  Bot,
  Check,
  Clock3,
  LogOut,
  Mic2,
  RefreshCw,
  RadioTower,
  TriangleAlert,
  Trash2,
  Volume2,
  Wifi,
  X,
} from "lucide-react";
import styles from "@/app/admin/admin.module.css";
import { buildLatencyGroups } from "@/lib/admin-diagnostics";
import {
  formatClock,
  formatDuration,
  formatRate,
  metricLabel,
  type DiagnosticsOverview,
  type MetricAggregate,
  type SessionSummary,
} from "@/lib/observability";

const REFRESH_MS = 10_000;

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { cache: "no-store" });
  const payload = await response.json() as T & { error?: string };
  if (!response.ok) throw new Error(payload.error ?? `HTTP ${response.status}`);
  return payload;
}

export function AdminDashboard({ username }: { username: string }) {
  const [minutes, setMinutes] = useState(60);
  const [overview, setOverview] = useState<DiagnosticsOverview | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [selectedSessions, setSelectedSessions] = useState<Set<string>>(new Set());
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const [nextOverview, nextSessions] = await Promise.all([
        getJson<DiagnosticsOverview>(`/api/observability/overview?minutes=${minutes}`),
        getJson<SessionSummary[]>(`/api/observability/sessions?minutes=${minutes}&limit=100`),
      ]);
      setOverview(nextOverview);
      setSessions(nextSessions);
      const available = new Set(nextSessions.map((session) => session.voice_session_id));
      setSelectedSessions((current) => new Set([...current].filter((sessionId) => available.has(sessionId))));
      setUpdatedAt(new Date());
      setError("");
    } catch (cause) {
      if (cause instanceof Error && cause.message === "未登录") window.location.reload();
      setError(cause instanceof Error ? cause.message : "诊断数据加载失败");
    } finally {
      setRefreshing(false);
    }
  }, [minutes]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const groups = useMemo(() => buildLatencyGroups(overview?.metrics ?? []), [overview]);
  const serviceHealth = useMemo(() => buildServiceHealth(overview?.metrics ?? []), [overview]);
  const sortedMetrics = useMemo(
    () => [...(overview?.metrics ?? [])].sort((a, b) => b.p95_ms - a.p95_ms),
    [overview],
  );
  const allSessionsSelected = sessions.length > 0 && sessions.every(
    (session) => selectedSessions.has(session.voice_session_id),
  );

  async function logout() {
    await fetch("/api/admin/logout", { method: "POST" });
    window.location.reload();
  }

  function toggleSession(sessionId: string) {
    setSelectedSessions((current) => {
      const next = new Set(current);
      if (next.has(sessionId)) next.delete(sessionId);
      else next.add(sessionId);
      return next;
    });
  }

  function toggleAllSessions() {
    setSelectedSessions(
      allSessionsSelected
        ? new Set()
        : new Set(sessions.map((session) => session.voice_session_id)),
    );
  }

  async function deleteSelectedSessions() {
    const sessionIds = [...selectedSessions];
    if (!sessionIds.length || deleting) return;
    setDeleting(true);
    try {
      const response = await fetch("/api/observability/sessions", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_ids: sessionIds }),
      });
      const payload = await response.json() as { error?: string };
      if (!response.ok) throw new Error(payload.error ?? `HTTP ${response.status}`);
      setSelectedSessions(new Set());
      setConfirmDelete(false);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "历史会话删除失败");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <main className={styles.shell}>
      <header className={styles.header}>
        <div className={styles.identity}>
          <span className={styles.logo}><RadioTower /></span>
          <div><span>OPENREALTIME / ADMIN</span><h1>运行诊断</h1></div>
        </div>
        <div className={styles.headerActions}>
          <label>观察窗口<select value={minutes} onChange={(event) => setMinutes(Number(event.target.value))}><option value={15}>15 分钟</option><option value={60}>1 小时</option><option value={360}>6 小时</option><option value={1440}>24 小时</option><option value={10080}>7 天</option></select></label>
          <button type="button" onClick={() => void refresh()} aria-label="刷新数据"><RefreshCw className={refreshing ? styles.spinning : ""} /></button>
          <button type="button" onClick={() => void logout()} aria-label={`退出 ${username}`}><LogOut /></button>
        </div>
      </header>

      <section className={styles.statusLine}>
        <span><i />实时采样中</span>
        <p>{updatedAt ? `${updatedAt.toLocaleTimeString("zh-CN", { hour12: false })} 更新` : "正在连接诊断服务"}</p>
      </section>
      {error ? <div className={styles.errorBanner}><TriangleAlert />{error}</div> : null}

      <section className={styles.summaryGrid} aria-label="运行概览">
        <SummaryCard label="有效回复成功率" value={formatRate(overview?.success_rate ?? null)} hint={`${overview?.successful_turn_count ?? 0} / ${Math.max(0, (overview?.turn_count ?? 0) - (overview?.interrupted_count ?? 0))} turns · ${overview?.interrupted_count ?? 0} 次正常打断`} />
        <SummaryCard label="模型服务超时" value={String(serviceHealth.modelTimeouts)} hint="LLM / TTS / ASR" alert={serviceHealth.modelTimeouts > 0} />
        <SummaryCard label="断连 / 异常" value={String(serviceHealth.disconnects)} hint={`${overview?.error_count ?? 0} 个错误`} alert={serviceHealth.disconnects > 0 || (overview?.error_count ?? 0) > 0} />
        <SummaryCard label="播放稳定度" value={serviceHealth.smoothness === null ? "—" : `${serviceHealth.smoothness.toFixed(1)}%`} hint={`${serviceHealth.underruns} 次欠载`} alert={serviceHealth.smoothness !== null && serviceHealth.smoothness < 98} />
      </section>

      <section className={styles.section}>
        <div className={styles.sectionHeading}><div><span>PIPELINE LATENCY</span><h2>链路耗时</h2></div><p>P50 / P95，覆盖 ASR、模型、TTS、网络和终端播放</p></div>
        <div className={styles.latencyGrid}>
          {groups.map((group, index) => <LatencyCard key={group.id} group={group} icon={[Mic2, Bot, Volume2, Clock3, Wifi, AudioLines][index]} />)}
        </div>
      </section>

      <section className={styles.serviceStrip}>
        <ServiceMetric icon={Mic2} label="ASR 连接" value={formatDuration(serviceHealth.asrConnect?.p95_ms ?? null)} sub="P95 会话建立" />
        <ServiceMetric icon={Volume2} label="TTS 连接 / 首包" value={formatDuration(serviceHealth.ttsFirstPacket?.p95_ms ?? null)} sub="P95，含连接复用" />
        <ServiceMetric icon={Bot} label="大模型首响" value={formatDuration(serviceHealth.llm?.p95_ms ?? null)} sub={`${serviceHealth.llm?.timeout_count ?? 0} 次超时`} />
        <ServiceMetric icon={Activity} label="端到端首播" value={formatDuration(groups.find((group) => group.id === "e2e")?.p95_ms ?? null)} sub="用户停说到听见声音" />
      </section>

      <section className={styles.twoColumn}>
        <div className={styles.panel}>
          <div className={styles.panelHeading}><div><span>SESSIONS</span><h2>历史会话</h2></div><div className={styles.historyActions}><button type="button" onClick={toggleAllSessions} disabled={!sessions.length}>{allSessionsSelected ? "取消全选" : "全选"}</button><button type="button" data-danger disabled={!selectedSessions.size} onClick={() => setConfirmDelete(true)}><Trash2 />删除 {selectedSessions.size || ""}</button><b>{sessions.length}</b></div></div>
          <div className={styles.sessionList}>
            {sessions.map((session) => (
              <div className={styles.sessionRow} data-selected={selectedSessions.has(session.voice_session_id)} key={session.voice_session_id}>
                <label className={styles.sessionSelect} title="选择会话"><input type="checkbox" checked={selectedSessions.has(session.voice_session_id)} onChange={() => toggleSession(session.voice_session_id)} aria-label={`选择会话 ${session.voice_session_id}`} /><span><Check /></span></label>
                <Link href={`/admin/sessions/${encodeURIComponent(session.voice_session_id)}`}>
                  <span className={styles.sessionPulse} data-alert={session.error_count > 0 || session.timeout_count > 0} />
                  <span><strong>{session.voice_session_id.slice(0, 16)}</strong><small>{formatClock(session.last_event_at)} · {session.event_count} 条事件</small></span>
                  <span className={styles.badges}><i>{session.turn_count} turns</i>{session.timeout_count ? <i data-alert>{session.timeout_count} timeout</i> : null}{session.error_count ? <i data-alert>{session.error_count} error</i> : null}</span>
                  <ArrowUpRight />
                </Link>
              </div>
            ))}
            {!sessions.length ? <p className={styles.empty}>观察窗口内暂无会话</p> : null}
          </div>
        </div>

        <div className={styles.panel}>
          <div className={styles.panelHeading}><div><span>ALL METRICS</span><h2>性能明细</h2></div><b>{sortedMetrics.length}</b></div>
          <div className={styles.metricTable}><table><thead><tr><th>指标</th><th>样本</th><th>P50</th><th>P95</th><th>超时</th><th>错误</th></tr></thead><tbody>{sortedMetrics.map((metric) => <tr key={metric.name}><td><strong>{metricLabel(metric.name)}</strong><small>{metric.name}</small></td><td>{metric.sample_count}</td><td>{formatDuration(metric.p50_ms)}</td><td>{formatDuration(metric.p95_ms)}</td><td data-alert={metric.timeout_count > 0}>{metric.timeout_count}</td><td data-alert={metric.error_count > 0}>{metric.error_count}</td></tr>)}</tbody></table>{!sortedMetrics.length ? <p className={styles.empty}>等待指标样本</p> : null}</div>
        </div>
      </section>

      {confirmDelete ? <div className={styles.confirmBackdrop} role="presentation" onMouseDown={(event) => event.target === event.currentTarget && !deleting && setConfirmDelete(false)}><section className={styles.confirmDialog} role="dialog" aria-modal="true" aria-labelledby="delete-session-title"><button className={styles.confirmClose} type="button" onClick={() => setConfirmDelete(false)} disabled={deleting} aria-label="关闭"><X /></button><span className={styles.confirmIcon}><Trash2 /></span><div><small>DESTRUCTIVE ACTION</small><h2 id="delete-session-title">删除 {selectedSessions.size} 个历史会话？</h2><p>对应的对话正文、链路耗时、性能指标和诊断日志将被永久删除，操作不可恢复。活动中的会话不会被删除。</p></div><div className={styles.confirmActions}><button type="button" onClick={() => setConfirmDelete(false)} disabled={deleting}>取消</button><button type="button" data-danger onClick={() => void deleteSelectedSessions()} disabled={deleting}><Trash2 />{deleting ? "正在删除…" : "确认永久删除"}</button></div></section></div> : null}
    </main>
  );
}

function SummaryCard({ label, value, hint, alert = false }: { label: string; value: string; hint: string; alert?: boolean }) {
  return <article className={styles.summaryCard} data-alert={alert}><span>{label}</span><strong>{value}</strong><small>{hint}</small></article>;
}

function LatencyCard({ group, icon: Icon }: { group: ReturnType<typeof buildLatencyGroups>[number]; icon: typeof Mic2 }) {
  return <article className={styles.latencyCard}><span className={styles.metricIcon}><Icon /></span><div><span>{group.label}</span><strong>{formatDuration(group.p95_ms)}</strong><small>P50 {formatDuration(group.p50_ms)} · {group.sample_count} 样本</small></div>{group.timeout_count || group.error_count ? <i>{group.timeout_count + group.error_count}</i> : null}</article>;
}

function ServiceMetric({ icon: Icon, label, value, sub }: { icon: typeof Mic2; label: string; value: string; sub: string }) {
  return <article><Icon /><div><span>{label}</span><strong>{value}</strong><small>{sub}</small></div></article>;
}

function buildServiceHealth(metrics: MetricAggregate[]) {
  const asrConnect = metrics.find((metric) => metric.name === "asr.start_session") ?? null;
  const ttsFirstPacket = metrics.find((metric) => metric.name === "tts.connection_setup")
    ?? metrics.find((metric) => metric.name === "tts.time_to_first_audio")
    ?? null;
  const llm = metrics.find((metric) => /^provider\..+\.chat(?:\.stream)?$/.test(metric.name)) ?? null;
  const providerMetrics = metrics.filter((metric) => metric.name.startsWith("provider.") || metric.name.startsWith("asr."));
  const modelTimeouts = providerMetrics.reduce((sum, metric) => sum + metric.timeout_count, 0);
  const disconnects = metrics.filter((metric) => /disconnect|connection_(?:closed|lost)|transport_disconnect|session_restarted/.test(metric.name)).reduce((sum, metric) => sum + metric.sample_count, 0);
  const playbackSamples = metrics.find((metric) => metric.name === "client.network_jitter")?.sample_count ?? 0;
  const underruns = metrics.find((metric) => metric.name === "client.playback_underrun")?.sample_count ?? 0;
  const smoothness = playbackSamples ? Math.max(0, (1 - underruns / playbackSamples) * 100) : null;
  return { asrConnect, ttsFirstPacket, llm, modelTimeouts, disconnects, underruns, smoothness };
}

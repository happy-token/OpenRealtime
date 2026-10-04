"use client";
import { useLanguage } from "@/components/language/language-provider";

import { useEffect, useMemo, useState } from "react";
import { Bot, ChevronDown, Flag, Mic2, Play, ScrollText } from "lucide-react";
import { SelectMenu, type SelectMenuOption } from "@/components/ui/select-menu";
import { buildSessionMetricAggregates } from "@/lib/admin-diagnostics";
import {
  formatClock,
  formatDuration,
  stageLabel,
  type DebugLogEntry,
  type DebugLogTimeline,
  type DebugLogStage,
  type SessionDetail,
  type SessionSummary,
} from "@/lib/observability";
import styles from "./decision-log-screen.module.css";

const DEBUG_LOG_LIMIT = 500;
const SESSION_WINDOW_MINUTES = 1440;
const SESSION_LIST_LIMIT = 100;

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { cache: "no-store" });
  const payload = await response.json() as T & { error?: string };
  if (!response.ok) throw new Error(payload.error ?? `HTTP ${response.status}`);
  return payload;
}

export function DecisionLogScreen() {
  const { t } = useLanguage();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState("");
  const [timeline, setTimeline] = useState<DebugLogEntry[]>([]);
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [loadingSessions, setLoadingSessions] = useState(true);
  const [loadingTimeline, setLoadingTimeline] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    setLoadingSessions(true);
    getJson<SessionSummary[]>(`/api/observability/sessions?minutes=${SESSION_WINDOW_MINUTES}&limit=${SESSION_LIST_LIMIT}`)
      .then((nextSessions) => {
        if (!active) return;
        setSessions(nextSessions);
        if (nextSessions.length) setSelectedSessionId(nextSessions[0].voice_session_id);
      })
      .catch((cause) => active && setError(cause instanceof Error ? cause.message : "会话列表加载失败"))
      .finally(() => active && setLoadingSessions(false));
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!selectedSessionId) {
      setTimeline([]);
      setDetail(null);
      return;
    }
    let active = true;
    setLoadingTimeline(true);
    setError("");
    Promise.all([
      getJson<DebugLogTimeline>(`/api/observability/sessions/${encodeURIComponent(selectedSessionId)}/debug-log?limit=${DEBUG_LOG_LIMIT}`),
      getJson<SessionDetail>(`/api/observability/sessions/${encodeURIComponent(selectedSessionId)}`),
    ])
      .then(([nextTimeline, nextDetail]) => {
        if (!active) return;
        setTimeline(nextTimeline.entries);
        setDetail(nextDetail);
      })
      .catch((cause) => active && setError(cause instanceof Error ? cause.message : "决策日志加载失败"))
      .finally(() => active && setLoadingTimeline(false));
    return () => { active = false; };
  }, [selectedSessionId]);

  const bargeInMetric = useMemo(() => {
    if (!detail) return null;
    return buildSessionMetricAggregates(detail).find((metric) => metric.name === "barge_in.time_to_client_stop") ?? null;
  }, [detail]);

  const sessionOptions: SelectMenuOption<string>[] = sessions.map((session) => ({
    value: session.voice_session_id,
    label: `${session.voice_session_id.slice(0, 16)} · ${formatClock(session.last_event_at)}`,
    description: `${session.turn_count} turns · ${session.event_count} 条事件`,
  }));

  return (
    <div className={styles.page}>
      <h1><ScrollText aria-hidden="true" />{t("决策日志")}</h1>
      <p className={styles.intro}>{t("查看语义完整度与语义打断的判断依据，以及打断发生到客户端确认停播的延迟。")}</p>

      <section className={styles.section}>
        <label className={styles.sessionPicker}>
          <span>{t("选择会话")}</span>
          {sessionOptions.length
            ? <SelectMenu fullWidth value={selectedSessionId || sessionOptions[0].value} options={sessionOptions} ariaLabel={t("选择会话")} onChange={setSelectedSessionId} />
            : <p className={styles.empty}>{loadingSessions ? t("正在加载会话列表…") : t("观察窗口内暂无会话")}</p>}
        </label>
      </section>

      {error ? <p className={styles.error}>{t(error)}</p> : null}

      <section className={styles.section}>
        <h2>{t("打断响应延迟")}</h2>
        {bargeInMetric
          ? <div className={styles.bargeInCard}>
            <span className={styles.bargeInIcon}><Flag /></span>
            <div>
              <div className={styles.bargeInStats}>
                <span><small>P50</small><strong>{formatDuration(bargeInMetric.p50_ms)}</strong></span>
                <span><small>P95</small><strong>{formatDuration(bargeInMetric.p95_ms)}</strong></span>
                <span><small>{t("样本")}</small><strong>{bargeInMetric.sample_count}</strong></span>
              </div>
              <small>{t("检测到打断到客户端确认停播")}</small>
            </div>
          </div>
          : <p className={styles.empty}>{loadingTimeline ? t("正在加载…") : t("本会话未发生打断")}</p>}
      </section>

      <section className={styles.section}>
        <h2>{t("判断时间线")}</h2>
        <div className={styles.timeline}>
          {timeline.map((entry) => <TimelineEntry key={entry.event_id} entry={entry} />)}
          {!timeline.length && !loadingTimeline ? <p className={styles.empty}>{t("该会话暂无决策日志记录")}</p> : null}
        </div>
      </section>
    </div>
  );
}

function TimelineEntry({ entry }: { entry: DebugLogEntry }) {
  const { t } = useLanguage();
  const Icon = stageIcon(entry.stage);
  const hasDetail = Object.keys(entry.detail).length > 0;
  return (
    <details className={styles.entry} data-stage={entry.stage}>
      <summary>
        <span className={styles.entryIcon}><Icon /></span>
        <span className={styles.entryCopy}>
          <small>{t(stageLabel(entry.stage))}</small>
          <strong>{entry.summary}</strong>
        </span>
        <time>{formatClock(entry.occurred_at)}</time>
        {hasDetail ? <ChevronDown /> : null}
      </summary>
      {hasDetail ? <pre className={styles.entryDetail}>{JSON.stringify(entry.detail, null, 2)}</pre> : null}
    </details>
  );
}

function stageIcon(stage: string) {
  const icons: Record<DebugLogStage, typeof Mic2> = {
    eot: Mic2,
    interruption: Flag,
    turn: Bot,
    playback: Play,
  };
  return icons[stage as DebugLogStage] ?? ScrollText;
}

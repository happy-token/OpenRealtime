"use client";

import { BackLink } from "@/components/workspace/back-link";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  AudioLines,
  AudioWaveform,
  Bot,
  BrainCircuit,
  Bug,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Clock3,
  FileWarning,
  Flag,
  Headphones,
  LocateFixed,
  Mic2,
  Play,
  Radio,
  ScanSearch,
  ScrollText,
  TriangleAlert,
  UserRound,
  Wifi,
  Workflow,
} from "lucide-react";
import adminStyles from "@/app/admin/admin.module.css";
import styles from "@/app/admin/sessions/[sessionId]/session-replay.module.css";
import {
  buildDiagnosticLogs,
  buildReplayTurns,
  buildSessionMetricAggregates,
  buildSessionPipelineStages,
  type ConversationReplayItem,
  type ReplayEventStage,
  type ReplayTimelineEvent,
  type ReplayTurn,
  type SessionPipelineStage,
} from "@/lib/admin-diagnostics";
import { formatClock, formatDuration, metricLabel, type SessionDetail } from "@/lib/observability";

export function SessionDiagnostics({ sessionId }: { sessionId: string }) {
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [conversation, setConversation] = useState<ConversationReplayItem[]>([]);
  const [error, setError] = useState("");
  const [logMode, setLogMode] = useState<"errors" | "all">("errors");
  const [showLogs, setShowLogs] = useState(false);
  const turnRefs = useRef(new Map<number, HTMLElement>());

  useEffect(() => {
    let active = true;
    Promise.all([
      getJson<SessionDetail>(`/api/observability/sessions/${encodeURIComponent(sessionId)}`),
      getJson<ConversationReplayItem[]>(`/api/observability/sessions/${encodeURIComponent(sessionId)}/conversation`),
    ])
      .then(([nextDetail, nextConversation]) => {
        if (!active) return;
        setDetail(nextDetail);
        setConversation(nextConversation);
      })
      .catch((cause) => active && setError(cause instanceof Error ? cause.message : "会话加载失败"));
    return () => { active = false; };
  }, [sessionId]);

  const turns = useMemo(
    () => detail ? buildReplayTurns(detail, conversation) : [],
    [conversation, detail],
  );
  const abnormalTurns = turns.filter((turn) => turn.abnormal);
  const logs = detail ? buildDiagnosticLogs(detail) : [];
  const events = logMode === "errors" ? logs : [...(detail?.events ?? [])].reverse();
  const playbackTurns = turns.filter((turn) => (turn.latency?.playback_underruns ?? 0) > 0);
  const averageJitter = average(turns.map((turn) => turn.latency?.network_jitter_ms ?? null));
  const sessionMetrics = useMemo(
    () => detail ? buildSessionMetricAggregates(detail) : [],
    [detail],
  );
  const pipelineStages = useMemo(
    () => buildSessionPipelineStages(sessionMetrics),
    [sessionMetrics],
  );
  const performanceMetrics = useMemo(
    () => [...sessionMetrics].sort((left, right) => right.p95_ms - left.p95_ms),
    [sessionMetrics],
  );

  function jumpToTurn(generation: number) {
    turnRefs.current.get(generation)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  return (
    <main className={adminStyles.shell}>
      <header className={adminStyles.detailHeader}>
        <div><BackLink href="/admin" label="返回看板" /><h1>{sessionId.slice(0, 24)}</h1><p>{detail ? `${fullTimestamp(detail.summary.first_event_at)} — ${fullTimestamp(detail.summary.last_event_at)}` : "正在读取会话数据"}</p></div>
        <div className={adminStyles.headerBadges}><i>{detail?.summary.turn_count ?? 0} turns</i><i data-alert={(detail?.summary.timeout_count ?? 0) > 0}>{detail?.summary.timeout_count ?? 0} timeout</i><i data-alert={(detail?.summary.error_count ?? 0) > 0}>{detail?.summary.error_count ?? 0} error</i></div>
      </header>
      {error ? <div className={adminStyles.errorBanner}><TriangleAlert />{error}</div> : null}

      <section className={adminStyles.summaryGrid}>
        <Summary icon={Clock3} label="端到端 P95" value={formatDuration(percentile(turns.map((turn) => turn.latency?.first_audio_ms ?? null), 0.95))} />
        <Summary icon={Wifi} label="平均网络抖动" value={formatDuration(averageJitter)} />
        <Summary icon={Bug} label="播放不稳定轮次" value={`${playbackTurns.length} / ${turns.length}`} alert={playbackTurns.length > 0} />
        <Summary icon={FileWarning} label="异常轮次" value={`${abnormalTurns.length} / ${turns.length}`} alert={abnormalTurns.length > 0} />
      </section>

      <section className={styles.performanceSection} aria-label="本会话链路耗时">
        <div className={styles.performanceHeading}>
          <div><h2>本会话链路耗时</h2></div>
          <p>按本会话全部轮次聚合 · P50 / P95 / P99</p>
        </div>
        <div className={styles.pipelineChain}>
          {pipelineStages.map((stage, index) => (
            <PipelineStageCard key={stage.id} stage={stage} index={index} />
          ))}
        </div>
      </section>

      <section className={styles.performancePanel} aria-label="本会话性能明细">
        <header><div><h2>性能明细</h2></div><span>{performanceMetrics.length} 项指标</span></header>
        <div className={styles.performanceTable}>
          <table>
            <thead><tr><th>指标</th><th>样本</th><th>P50</th><th>P95</th><th>P99</th><th>最大</th><th>超时</th><th>错误</th></tr></thead>
            <tbody>{performanceMetrics.map((metric) => <tr key={metric.name}><td><strong>{metricLabel(metric.name)}</strong><small>{metric.name}</small></td><td>{metric.sample_count}</td><td>{formatDuration(metric.p50_ms)}</td><td>{formatDuration(metric.p95_ms)}</td><td>{formatDuration(metric.p99_ms)}</td><td>{formatDuration(metric.max_ms)}</td><td data-alert={metric.timeout_count > 0}>{metric.timeout_count}</td><td data-alert={metric.error_count > 0}>{metric.error_count}</td></tr>)}</tbody>
          </table>
          {!performanceMetrics.length ? <p className={styles.emptyPerformance}>本会话还没有可聚合的耗时样本。</p> : null}
        </div>
      </section>

      <section className={styles.recordingBar} aria-label="会话录音">
        <span><Headphones /></span>
        <div><strong>会话录音</strong><p>当前会话未保存原始录音；启用录音保留策略后可在此播放并与消息时间点联动。</p></div>
        <button disabled><AudioLines />暂无录音</button>
      </section>

      {abnormalTurns.length ? (
        <nav className={styles.issueNavigator} aria-label="异常轮次定位">
          <div><AlertTriangle /><span><strong>发现 {abnormalTurns.length} 个异常轮次</strong><small>点击可直接定位到对应对话</small></span></div>
          <div>{abnormalTurns.map((turn) => <button key={turn.generation} onClick={() => jumpToTurn(turn.generation)}><LocateFixed />轮次 {turn.generation}<i>{turn.issues[0]?.label}</i></button>)}</div>
        </nav>
      ) : null}

      <section className={styles.replayPanel}>
        <header className={styles.replayHeading}><div><span><Radio /></span><div><h2>对话复盘</h2></div></div><p>普通状态已压缩，异常事件保持展开</p></header>
        <div className={styles.turnTimeline}>
          {turns.map((turn) => (
            <TurnReplay
              key={turn.generation}
              turn={turn}
              register={(element) => {
                if (element) turnRefs.current.set(turn.generation, element);
                else turnRefs.current.delete(turn.generation);
              }}
            />
          ))}
          {!turns.length ? <p className={styles.emptyReplay}>该会话没有可复盘的对话轮次。旧会话可能早于对话记录功能启用时间。</p> : null}
        </div>
      </section>

      <section className={adminStyles.panel}>
        <button className={styles.logsToggle} onClick={() => setShowLogs((value) => !value)} aria-expanded={showLogs}>
          <span><ScrollText /><b>底层诊断日志</b><small>{logs.length} 条异常 / {detail?.events.length ?? 0} 条全部</small></span><ChevronDown data-open={showLogs} />
        </button>
        {showLogs ? <><div className={styles.logControls}><button data-active={logMode === "errors"} onClick={() => setLogMode("errors")}><FileWarning />异常 {logs.length}</button><button data-active={logMode === "all"} onClick={() => setLogMode("all")}><ScrollText />全部 {detail?.events.length ?? 0}</button></div><div className={adminStyles.logList}>{events.map((event) => <LogEvent key={event.event_id} event={event} />)}{!events.length ? <p className={adminStyles.empty}>没有符合条件的日志</p> : null}</div></> : null}
      </section>
    </main>
  );
}

function PipelineStageCard({ stage, index }: { stage: SessionPipelineStage; index: number }) {
  const Icon = [Mic2, ScanSearch, BrainCircuit, Radio, AudioWaveform, Play][index] ?? Activity;
  const alert = stage.timeout_count > 0 || stage.error_count > 0;
  return (
    <article className={styles.pipelineStage} data-empty={!stage.metric_name} data-alert={alert}>
      <header><span><Icon /></span><i>{String(index + 1).padStart(2, "0")}</i></header>
      <div><strong>{stage.label}</strong><small>{stage.description}</small></div>
      <dl><div><dt>P50</dt><dd>{formatDuration(stage.p50_ms)}</dd></div><div><dt>P95</dt><dd>{formatDuration(stage.p95_ms)}</dd></div><div><dt>P99</dt><dd>{formatDuration(stage.p99_ms)}</dd></div></dl>
      <footer><span>{stage.sample_count} 个样本</span>{alert ? <b>{stage.timeout_count + stage.error_count} 个异常</b> : <small>{stage.metric_name ? "采样正常" : "暂无采样"}</small>}</footer>
      {index < 5 ? <ChevronRight className={styles.pipelineArrow} /> : null}
    </article>
  );
}

function TurnReplay({ turn, register }: { turn: ReplayTurn; register: (element: HTMLElement | null) => void }) {
  const userMessages = turn.messages.filter((message) => message.role === "user");
  const assistantMessages = turn.messages.filter((message) => message.role === "assistant");
  return (
    <article ref={register} className={styles.turn} data-abnormal={turn.abnormal}>
      <div className={styles.turnBoundary} aria-label={`轮次 ${turn.generation - 1} 到 ${turn.generation}`}>
        <span>{turn.generation - 1}</span><i /><span>{turn.generation}</span>
      </div>
      <div className={styles.turnBody}>
        <header><div><strong>轮次 {turn.generation}</strong><i data-abnormal={turn.abnormal}>{turn.abnormal ? "需要关注" : "正常"}</i></div><span>{turn.latency?.total_ms !== null && turn.latency ? `总耗时 ${formatDuration(turn.latency.total_ms)}` : "耗时样本不足"}</span></header>
        <div className={styles.conversationAxis}>
          {userMessages.map((message) => <ReplayMessage key={message.item_id} message={message} abnormal={turn.abnormal} />)}
          <TurnEventHub turn={turn} />
          {assistantMessages.map((message) => <ReplayMessage key={message.item_id} message={message} abnormal={turn.abnormal} />)}
        </div>
        {!turn.messages.length ? <p className={styles.missingConversation}>本轮仅有运行事件，没有已提交的对话文本。</p> : null}
        {turn.issues.map((issue) => <div className={styles.issueCard} key={issue.event_id}><AlertTriangle /><div><strong>{issue.label}</strong><p>{issue.detail}</p></div><time>{timeWithMilliseconds(issue.occurred_at)}</time></div>)}
        {turn.latency ? <div className={styles.turnMetrics}><span>ASR<strong>{formatDuration(turn.latency.asr_ms)}</strong></span><span>模型<strong>{formatDuration(turn.latency.llm_ms)}</strong></span><span>TTS<strong>{formatDuration(turn.latency.tts_ms)}</strong></span><span>首播<strong>{formatDuration(turn.latency.first_audio_ms)}</strong></span><span>抖动<strong>{formatDuration(turn.latency.network_jitter_ms)}</strong></span><span>卡顿<strong>{turn.latency.playback_underruns ? `${turn.latency.playback_underruns} 次` : "稳定"}</strong></span></div> : null}
      </div>
    </article>
  );
}

function TurnEventHub({ turn }: { turn: ReplayTurn }) {
  const boundary = turn.timeline_events.find((event) => event.turn_boundary);
  const promotedIds = new Set(turn.timeline_events.map((event) => event.event_id));
  const otherEvents = turn.events.filter((event) => !promotedIds.has(event.event_id));
  return (
    <details className={styles.eventHub}>
      <summary>
        <span className={styles.eventHubIcon}><Workflow /></span>
        <span className={styles.eventHubCopy}><strong>{turn.timeline_events.length} 个关键时间点</strong><small>{turn.state_summary}</small></span>
        <span className={styles.eventHubBoundary}>
          <small>{boundary ? "表达完成 / 轮次确认" : "本轮起点"}</small>
          <time>{timeWithMilliseconds(boundary?.occurred_at ?? turn.occurred_at)}</time>
          <i>{formatElapsed(boundary?.elapsed_ms ?? 0)}</i>
        </span>
        <ChevronDown />
      </summary>
      <div className={styles.eventTimeline}>
        {turn.timeline_events.map((event) => <TimelineEvent key={event.event_id} timelineEvent={event} />)}
        {!turn.timeline_events.length ? <p className={styles.noTimelineEvents}>本轮没有可投影的关键过程事件。</p> : null}
      </div>
      {otherEvents.length ? (
        <details className={styles.rawEvents}>
          <summary><CircleDot />其他 {otherEvents.length} 个底层事件<ChevronDown /></summary>
          <div>{otherEvents.map((event) => <RawEvent key={event.event_id} event={event} turnStartedAt={turn.occurred_at} />)}</div>
        </details>
      ) : null}
    </details>
  );
}

function TimelineEvent({ timelineEvent }: { timelineEvent: ReplayTimelineEvent }) {
  const Icon = eventStageIcon(timelineEvent.stage, timelineEvent.turn_boundary);
  return (
    <details className={styles.timelineEvent} data-stage={timelineEvent.stage} data-boundary={timelineEvent.turn_boundary}>
      <summary>
        <span className={styles.eventIdentity}><small>{stageLabel(timelineEvent.stage)}</small><strong>{timelineEvent.label}</strong>{timelineEvent.state_change ? <i>{timelineEvent.state_change}</i> : null}</span>
        <span className={styles.eventNode}><Icon /></span>
        <span className={styles.eventTimestamp}><time>{timeWithMilliseconds(timelineEvent.occurred_at)}</time><small>{formatElapsed(timelineEvent.elapsed_ms)}</small></span>
      </summary>
      <EventPayload event={timelineEvent.event} />
    </details>
  );
}

function RawEvent({ event, turnStartedAt }: { event: SessionDetail["events"][number]; turnStartedAt: string }) {
  return (
    <details>
      <summary><time>{timeWithMilliseconds(event.occurred_at)}</time><span>{metricLabel(event.name)}</span><i>{formatElapsed(Math.max(0, Date.parse(event.occurred_at) - Date.parse(turnStartedAt)))}</i><ChevronDown /></summary>
      <EventPayload event={event} />
    </details>
  );
}

function EventPayload({ event }: { event: SessionDetail["events"][number] }) {
  return (
    <div className={styles.eventPayload}>
      <div><span>事件</span><code>{event.name}</code></div>
      <div><span>结果</span><b data-outcome={event.outcome}>{event.outcome}</b></div>
      <div><span>耗时</span><b>{formatDuration(event.duration_ms)}</b></div>
      {event.error_message ? <p>{event.error_message}</p> : null}
      {Object.keys(event.attributes).length ? <pre>{JSON.stringify(event.attributes, null, 2)}</pre> : null}
    </div>
  );
}

function ReplayMessage({ message, abnormal }: { message: ConversationReplayItem; abnormal: boolean }) {
  const user = message.role === "user";
  return <div className={styles.message} data-role={message.role}><span>{user ? <UserRound /> : <Bot />}</span><div><header><strong>{user ? "用户" : "OpenRealtime"}</strong><time>{timeWithMilliseconds(message.occurred_at)}</time>{abnormal ? <i>异常轮次</i> : null}</header><p>{message.text}</p><small>{messageStatus(message.status)}</small></div></div>;
}

function LogEvent({ event }: { event: ReturnType<typeof buildDiagnosticLogs>[number] | SessionDetail["events"][number] }) {
  const name = event.name;
  const severity = event.severity;
  const message = "message" in event ? event.message : event.error_message ?? event.outcome;
  return <article data-severity={severity}><time>{formatClock(event.occurred_at)}</time><span>{severity}</span><div><strong>{metricLabel(name)}</strong><small>{name}</small>{message ? <p>{String(message)}</p> : null}</div>{"duration_ms" in event && event.duration_ms !== null ? <b>{formatDuration(event.duration_ms)}</b> : null}</article>;
}

function Summary({ icon: Icon, label, value, alert = false }: { icon: typeof Clock3; label: string; value: string; alert?: boolean }) {
  return <article className={adminStyles.summaryCard} data-alert={alert}><Icon /><span>{label}</span><strong>{value}</strong></article>;
}

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { cache: "no-store" });
  const payload = await response.json() as T & { error?: string };
  if (!response.ok) throw new Error(payload.error ?? `HTTP ${response.status}`);
  return payload;
}

function messageStatus(status: string): string {
  const labels: Record<string, string> = {
    committed: "已提交",
    completed: "已完成",
    failed: "失败",
    cancelled: "已取消",
    interrupted: "被打断",
    in_progress: "生成中",
  };
  return labels[status] ?? status;
}

function eventStageIcon(stage: ReplayEventStage, boundary: boolean) {
  if (boundary) return Flag;
  return { input: Mic2, endpoint: ScanSearch, model: BrainCircuit, tts: AudioWaveform, playback: Play, state: Activity, system: CircleDot }[stage];
}

function stageLabel(stage: ReplayEventStage): string {
  return { input: "用户输入", endpoint: "轮次判断", model: "模型处理", tts: "语音合成", playback: "终端播放", state: "对话状态", system: "系统事件" }[stage];
}

function formatElapsed(value: number): string {
  if (value < 1000) return `+${Math.round(value)}ms`;
  return `+${(value / 1000).toFixed(value < 10_000 ? 2 : 1)}s`;
}

function timeWithMilliseconds(value: string): string {
  const date = new Date(value);
  return `${date.toLocaleTimeString("zh-CN", { hour12: false })}.${String(date.getMilliseconds()).padStart(3, "0")}`;
}

function fullTimestamp(value: string): string {
  const date = new Date(value);
  return `${date.toLocaleDateString("zh-CN")} ${timeWithMilliseconds(value)}`;
}

function average(values: Array<number | null>): number | null {
  const present = values.filter((value): value is number => value !== null);
  return present.length ? present.reduce((sum, value) => sum + value, 0) / present.length : null;
}

function percentile(values: Array<number | null>, ratio: number): number | null {
  const present = values.filter((value): value is number => value !== null).sort((a, b) => a - b);
  return present.length ? present[Math.min(present.length - 1, Math.floor(present.length * ratio))] : null;
}

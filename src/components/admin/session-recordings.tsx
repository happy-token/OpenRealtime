"use client";

import { useEffect, useRef, useState } from "react";
import type { SessionRecordingPage, SessionRecordingRow } from "@/lib/session-recordings";
import styles from "./diagnostics-workspace.module.css";

const statusLabel = { available: "可读取", expired: "已过期", deleted: "已删除", unavailable: "暂不可用" };
export function SessionRecordings({ sessionId, preview = false }: { sessionId: string; preview?: boolean }) {
  const [page, setPage] = useState<SessionRecordingPage | null>(null);
  const [rows, setRows] = useState<SessionRecordingRow[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<SessionRecordingRow | null>(null);
  const [audioError, setAudioError] = useState("");
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => { active.current?.abort(); active.current = null; }, [sessionId]);
  const load = async (refresh = false) => {
    if (preview || active.current || (!refresh && rows.length >= 2000)) return;
    const controller = new AbortController(); active.current = controller;
    const timeout = setTimeout(() => controller.abort(), 15_000);
    setBusy(true); setError("");
    if (refresh) { setSelected(null); setAudioError(""); }
    const cursor = !refresh && page?.next_cursor ? `&after_sequence=${encodeURIComponent(page.next_cursor)}` : "";
    try {
      const response = await fetch(`/api/observability/sessions/${encodeURIComponent(sessionId)}/recordings?limit=200${cursor}`, { cache: "no-store", signal: controller.signal });
      const next: SessionRecordingPage = await response.json();
      if (controller.signal.aborted || active.current !== controller) return;
      if (!response.ok || next.voice_session_id !== sessionId || !Array.isArray(next.items)) throw new Error("录音目录读取失败，请重试。");
      setPage(next);
      setRows(previous => refresh ? next.items : [...new Map([...previous, ...next.items].map(row => [row.item_id, row])).values()]);
    } catch (cause) {
      if (active.current === controller) setError(controller.signal.aborted ? "录音目录读取超时，请重试。" : cause instanceof Error ? cause.message : "录音目录暂不可用。");
    } finally {
      clearTimeout(timeout);
      if (active.current === controller) { active.current = null; setBusy(false); }
    }
  };
  return <section className={styles.panel} aria-label="会话录音">
    <div className={styles.panelhead}><h2>会话录音</h2><button disabled={preview || busy} onClick={() => void load(true)}>{busy ? "正在读取…" : page ? "刷新录音" : "查看录音"}</button></div>
    <p className={styles.note}>输入与已发送音频分别保存。已发送不代表已播放；片段可能因采集或存储异常缺失。录音保留 7 天，已标记保留的片段除外。</p>
    {preview ? <p className={styles.note}>预览页面不读取真实录音。</p> : null}
    {error ? <p className={styles.error} role="alert">{error}</p> : null}
    {page?.storage_status === "not-configured" ? <p className={styles.note}>此服务未配置录音存储。</p> : null}
    {page && !rows.length ? <p className={styles.empty}>未找到已保存的录音片段；不能据此判断用户没有说话。</p> : null}
    {selected ? <div className={styles.recordingPlayer}>
      <span>{selected.direction === "input" ? "用户输入" : "助手已发送"} · 轮次 {selected.generation} · {selected.sample_count / selected.sample_rate_hz} 秒</span>
      <audio key={selected.artifact_id} controls preload="none" src={selected.audio_url} onError={() => setAudioError("录音无法播放，可能已过期、删除或读取失败。请刷新目录核查。")} />
      <button onClick={() => { setSelected(null); setAudioError(""); }}>关闭播放器</button>
      {audioError ? <p role="alert">{audioError}</p> : null}
    </div> : null}
    {rows.length ? <div className={styles.recordingList}>{rows.map(row => <div key={row.item_id} className={styles.recordingRow}>
      <div><strong>{row.direction === "input" ? "用户输入" : "助手已发送"}</strong><small>轮次 {row.generation} · {(row.duration_ms / 1000).toFixed(2)} 秒 · {statusLabel[row.status]}{row.pinned ? " · 已保留" : ""}{!row.storage_durable ? " · 临时存储" : ""}{row.discontinuity ? " · 不连续" : ""}</small></div>
      <button disabled={row.status !== "available"} onClick={() => { setAudioError(""); setSelected(row); }}>播放片段</button>
    </div>)}</div> : null}
    {page?.next_cursor && rows.length < 2000 ? <div className={styles.note}><button disabled={busy} onClick={() => void load()}>{busy ? "正在读取…" : "加载更多录音"}</button><p>目录尚有下一页，当前片段列表不完整。</p></div> : null}
    {page?.next_cursor && rows.length >= 2000 ? <p className={styles.note}>已达到页面展示上限，剩余片段可通过 Agent 录音接口继续分页读取。</p> : null}
  </section>;
}

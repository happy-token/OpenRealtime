"use client";

import { useEffect, useRef, useState } from "react";
import type { SessionRecordingPage, SessionRecordingRow } from "@/lib/session-recordings";
import { projectPreservationResult } from "@/lib/recording-preservation";
import styles from "./diagnostics-workspace.module.css";

const statusLabel = { available: "可读取", expired: "已过期", deleted: "已删除", unavailable: "暂不可用" };
export function SessionRecordings({ sessionId, preview = false }: { sessionId: string; preview?: boolean }) {
  const [page, setPage] = useState<SessionRecordingPage | null>(null);
  const [rows, setRows] = useState<SessionRecordingRow[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<SessionRecordingRow | null>(null);
  const [audioError, setAudioError] = useState("");
  const [marking, setMarking] = useState(false);
  const [preservationUnknown, setPreservationUnknown] = useState(false);
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => { active.current?.abort(); active.current = null; }, [sessionId]);
  const readCatalog = async (controller: AbortController, refresh: boolean) => {
    if (refresh) { setSelected(null); setAudioError(""); }
    const cursor = !refresh && page?.next_cursor ? `&after_sequence=${encodeURIComponent(page.next_cursor)}` : "";
    const response = await fetch(`/api/observability/sessions/${encodeURIComponent(sessionId)}/recordings?limit=200${cursor}`, { cache: "no-store", signal: controller.signal });
    const next: SessionRecordingPage = await response.json();
    if (controller.signal.aborted || active.current !== controller) throw new Error("expired-recording-read");
    if (!response.ok || next.voice_session_id !== sessionId || !Array.isArray(next.items)) throw new Error("录音目录读取失败，请重试。");
    setPage(next); setPreservationUnknown(false);
    setRows(previous => refresh ? next.items : [...new Map([...previous, ...next.items].map(row => [row.item_id, row])).values()]);
  };
  const load = async (refresh = false) => {
    if (preview || active.current || (!refresh && rows.length >= 2000)) return;
    const controller = new AbortController(); active.current = controller;
    const timeout = setTimeout(() => controller.abort(), 15_000);
    setBusy(true); setError("");
    try {
      await readCatalog(controller, refresh);
    } catch (cause) {
      if (active.current === controller) setError(controller.signal.aborted ? "录音目录读取超时，请重试。" : cause instanceof Error ? cause.message : "录音目录暂不可用。");
    } finally {
      clearTimeout(timeout);
      if (active.current === controller) { active.current = null; setBusy(false); }
    }
  };
  const preserve = async () => {
    if (preview || active.current || preservationUnknown || page?.preservation?.status !== "unmarked") return;
    const controller = new AbortController(); active.current = controller;
    const timeout = setTimeout(() => controller.abort(), 15_000);
    setBusy(true); setMarking(true); setError("");
    let confirmed = false;
    try {
      const response = await fetch(`/api/observability/sessions/${encodeURIComponent(sessionId)}/recordings/preservation`, { method: "POST", cache: "no-store", signal: controller.signal });
      const result = await response.json();
      if (controller.signal.aborted || active.current !== controller) throw new Error("expired-preservation-result");
      if (!response.ok) throw new Error("preservation-unconfirmed");
      const view = projectPreservationResult(result, sessionId);
      confirmed = true;
      setPage(previous => previous ? { ...previous, preservation: view } : previous);
      await readCatalog(controller, true);
    } catch {
      if (active.current === controller) {
        setPreservationUnknown(!confirmed);
        setError(confirmed ? "会话已标记保留，但目录刷新未完成，请刷新核查片段。" : "保留结果尚未确认，后台可能仍在处理。请刷新录音目录核查后重试。");
      }
    } finally {
      clearTimeout(timeout);
      if (active.current === controller) { active.current = null; setBusy(false); setMarking(false); }
    }
  };
  const preservation = page?.preservation;
  return <section className={styles.panel} aria-label="会话录音">
    <div className={styles.panelhead}><h2>会话录音</h2><div className={styles.recordingActions}>
      <button disabled={preview || busy} onClick={() => void load(true)}>{busy && !marking ? "正在读取…" : page ? "刷新录音" : "查看录音"}</button>
      <button disabled={preview || busy || preservationUnknown || preservation?.status !== "unmarked"} onClick={() => void preserve()} title="保留该会话现有和后续录音，并保护对应排障记录。已过期或已删除的片段不会恢复。">{marking ? "正在保留…" : preservation?.status === "preserved" ? "已长期保留" : "长期保留"}</button>
    </div></div>
    <p className={styles.note}>输入与已发送音频分别保存。已发送不代表已播放；片段可能因采集或存储异常缺失。录音保留 7 天，已标记保留的片段除外。长期保留覆盖当前会话的现有和后续录音，已过期或已删除的片段不会恢复。</p>
    {preservation?.status === "preserved" ? <p className={styles.note} role="status">会话已标记保留 · 已验证保留 {preservation.preserved_segments} 段 · 等待完成 {preservation.pending_segments} 段 · 无法保留 {preservation.unavailable_segments} 段{!preservation.storage_durable ? "。当前为临时存储，重启后不保留。" : "。"}</p> : null}
    {page && (!preservation || preservation.status === "unavailable" || preservation.status === "unsupported") ? <p className={styles.note}>当前服务的保留状态暂不可用，可继续读取录音。</p> : null}
    {preservation?.status === "source-missing" ? <p className={styles.note}>尚无已核实的会话来源，暂不能标记保留。</p> : null}
    {preview ? <p className={styles.note}>预览页面不读取真实录音。</p> : null}
    {error ? <p className={styles.error} role="alert">{error}</p> : null}
    {page?.storage_status === "not-configured" ? <p className={styles.note}>此服务未配置录音存储。</p> : null}
    {page?.playback_source?.truncated || page?.playback_source?.collection_healthy === false ? <p className={styles.note}>播放回执证据尚不完整，当前数值仅覆盖已查到的回执；没有匹配回执不代表没有播放。</p> : null}
    {page?.playback_source && ["unavailable", "not-configured"].includes(page.playback_source.status) ? <p className={styles.note}>播放回执暂不可用，可继续读取录音。</p> : null}
    {page && !rows.length ? <p className={styles.empty}>未找到已保存的录音片段；不能据此判断用户没有说话。</p> : null}
    {selected ? <div className={styles.recordingPlayer}>
      <span>{selected.direction === "input" ? "用户输入" : "助手已发送"} · 轮次 {selected.generation} · {selected.sample_count / selected.sample_rate_hz} 秒</span>
      <audio key={selected.artifact_id} controls preload="none" src={selected.audio_url} onError={() => setAudioError("录音无法播放，可能已过期、删除或读取失败。请刷新目录核查。")} />
      <button onClick={() => { setSelected(null); setAudioError(""); }}>关闭播放器</button>
      {audioError ? <p role="alert">{audioError}</p> : null}
    </div> : null}
    {rows.length ? <div className={styles.recordingList}>{rows.map(row => <div key={row.item_id} className={styles.recordingRow}>
      <div><strong>{row.direction === "input" ? "用户输入" : "助手已发送"}</strong><small>轮次 {row.generation} · {(row.duration_ms / 1000).toFixed(2)} 秒 · {statusLabel[row.status]}{row.pinned ? " · 已保留" : ""}{!row.storage_durable ? " · 临时存储" : ""}{row.discontinuity ? " · 不连续" : ""}</small>
        {row.direction === "sent" ? <small title={`按原会话、输出epoch、语音及采样率匹配客户端回执。${row.playback?.overlap_samples !== null && row.playback?.overlap_samples !== undefined ? `该片段交集为 ${row.playback.overlap_samples} / ${row.sample_count} 个采样点。` : ""}仅表示客户端报告，不证明扬声器实际播出或用户听到。缺失回执时位置未知，不能推断未播放。`}>{row.playback?.status === "reported" && row.playback.overlap_samples !== null ? `回执覆盖 ${(row.playback.overlap_samples / row.sample_rate_hz).toFixed(3)} / ${(row.duration_ms / 1000).toFixed(3)} 秒` : "播放位置未知"}</small> : null}
      </div>
      <button disabled={row.status !== "available"} onClick={() => { setAudioError(""); setSelected(row); }}>播放片段</button>
    </div>)}</div> : null}
    {page?.next_cursor && rows.length < 2000 ? <div className={styles.note}><button disabled={busy} onClick={() => void load()}>{busy ? "正在读取…" : "加载更多录音"}</button><p>目录尚有下一页，当前片段列表不完整。</p></div> : null}
    {page?.next_cursor && rows.length >= 2000 ? <p className={styles.note}>已达到页面展示上限，剩余片段可通过 Agent 录音接口继续分页读取。</p> : null}
  </section>;
}

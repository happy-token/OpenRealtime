"use client";

import Image from "next/image";
import { SelectMenu } from "@/components/ui/select-menu";
import { MINIMAX_TALKING_PROMPT } from "@/lib/minimax-talking-prompt";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Film } from "lucide-react";
import { avatarApiRoot, fetchOwnedAvatar } from "@/lib/avatar-catalog-client";
import type { OwnedAvatarRecord } from "@/lib/avatar-records";
import { StudioConfigOverlay } from "./studio-config-overlay";
import { readLightweightDraft, selectIdle, matchingVariant, type LightweightDraft, type TalkingMethod } from "./lightweight-draft";
import {
  clearRecoverableGenerationTask,
  readRecoverableGenerationTask,
  saveRecoverableGenerationTask,
} from "@/lib/generation-task-recovery";
import styles from "./avatar-studio.module.css";
import actionStyles from "./avatar-action-studio.module.css";
import { useProviderKeyGate } from "@/components/provider-key/provider-key-gate";


function abortableDelay(milliseconds: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const cancel = () => {
      clearTimeout(timer);
      reject(new DOMException("Cancelled", "AbortError"));
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", cancel);
      resolve();
    }, milliseconds);
    signal.addEventListener("abort", cancel, { once: true });
    if (signal.aborted) cancel();
  });
}

export function AvatarLightweightConfig({ avatar, header, active, open, onOpenChange, onCreateAction, onSaved, initialActionId = "", initialMethod, previewBeforeSave = false, floating = false, onPreviewChange }: {
  avatar: OwnedAvatarRecord; header: ReactNode; active: boolean;
  open: boolean; onOpenChange: (open: boolean) => void; onCreateAction?: () => void; onSaved?: (variantId?: string) => void; initialActionId?: string; initialMethod?: TalkingMethod; previewBeforeSave?: boolean;
  floating?: boolean; onPreviewChange?: (preview: { url: string; name: string; kind?: "talking" } | null) => void;
}) {
  const [actions, setActions] = useState(avatar.actions);
  const ensureProviderKey = useProviderKeyGate();
  const [draft, setDraft] = useState<LightweightDraft>({ idle: "", method: "musetalk" });
  const [preview, setPreview] = useState<"idle" | "talking">("idle");
  const [notice, setNotice] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [duration, setDuration] = useState(10);
  const [wav2lipAudio, setWav2lipAudio] = useState<File | null>(null);
  const [lipForcingAudio, setLipForcingAudio] = useState<File | null>(null);
  const [museTalkAudio, setMuseTalkAudio] = useState<File | null>(null);
  const [wav2lipRights, setWav2lipRights] = useState(false);
  const [pendingReview, setPendingReview] = useState<{ jobId: string; sourceId: string; sourceUrl: string; videoUrl: string; method: "musetalk" | "wav2lip" | "lipforcing" } | null>(null);
  const generationLock = useRef(false);
  const generationAbort = useRef<AbortController | null>(null);
  const recoveryAttempt = useRef("");
  useEffect(() => () => generationAbort.current?.abort(), []);
  const video = useRef<HTMLVideoElement>(null);
  const key = `openrealtime:lightweight-draft:${avatar.avatar_id}`;
  const apiRoot = avatarApiRoot(avatar.avatar_id);
  useEffect(() => {
    try {
      const raw: unknown = JSON.parse(localStorage.getItem(key) || "null");
      const saved = readLightweightDraft(raw);
      const selected = initialActionId && avatar.actions.some(item => item.avatar_action_id === initialActionId && !item.deleted_at)
        ? selectIdle(saved, initialActionId)
        : saved;
      setDraft(initialMethod ? { ...selected, method: initialMethod } : floating && selected.method === "minimax" ? { ...selected, method: "musetalk" } : selected);
    } catch { setNotice("无法读取本机草稿，请重新选择素材。"); }
    setLoaded(true);
  }, [avatar.actions, floating, initialActionId, initialMethod, key]);
  useEffect(() => {
    if (!loaded) return;
    try { localStorage.setItem(key, JSON.stringify(draft)); }
    catch { setNotice("无法自动保存素材选择，请检查浏览器存储权限。"); }
  }, [draft, loaded, key]);
  useEffect(() => {
    if (!active) { video.current?.pause(); return; }
    const controller = new AbortController();
    void fetchOwnedAvatar(avatar.avatar_id, controller.signal).then(record => {
      if (record) setActions(record.actions);
    }).catch(error => {
      if (error instanceof Error && error.name === "AbortError") return;
      setNotice("动作库刷新失败，当前显示已加载的素材。重新进入此标签可重试。");
    });
    return () => controller.abort();
  }, [active, avatar.avatar_id]);
  const available = actions.filter(action => !action.deleted_at && action.video_url);
  const idle = available.find(action => action.avatar_action_id === draft.idle);
  const attachedVariant = idle?.talking_variants?.find(item => item.method === draft.method && !item.deleted_at && item.source_video_url === idle.video_url);
  const generatedVariant = matchingVariant(draft, idle?.video_url);
  const currentReview = pendingReview && idle?.video_url && pendingReview.sourceId === idle.avatar_action_id && pendingReview.sourceUrl === idle.video_url && pendingReview.method === draft.method ? pendingReview : null;
  const variant = currentReview ? { videoUrl: currentReview.videoUrl } : generatedVariant?.method === draft.method ? generatedVariant : attachedVariant ? { videoUrl: attachedVariant.video_url } : undefined;
  const pairedActions = available.filter(action => action.talking_variants?.some(item => !item.deleted_at && item.source_video_url === action.video_url));
  useEffect(() => {
    if (!active || !loaded || !idle?.video_url || variant || busy) return;
    const recoveryKey = `${draft.method}:${idle.avatar_action_id}:${idle.video_url}`;
    if (recoveryAttempt.current === recoveryKey) return;
    recoveryAttempt.current = recoveryKey;
    const controller = new AbortController();
    generationAbort.current = controller;

    if (draft.method === "musetalk" || draft.method === "wav2lip" || draft.method === "lipforcing") {
      const method = draft.method;
      const endpoint = `${apiRoot}/${encodeURIComponent(avatar.avatar_id)}/actions/${encodeURIComponent(idle.avatar_action_id)}/talking-variants/${method === "wav2lip" ? "generate-wav2lip" : method === "lipforcing" ? "generate-lipforcing" : "generate"}`;
      void fetch(endpoint, { cache: "no-store", signal: controller.signal }).then(async response => {
        const payload = await response.json();
        if (!response.ok || !payload.job) return;
        if (payload.job.sourceUrl && payload.job.sourceUrl !== idle.video_url) return;
        if (payload.job.state === "failed") {
          setNotice(payload.job.error || `上次 ${method === "wav2lip" ? "Wav2Lip" : method === "lipforcing" ? "Lip Forcing" : "MuseTalk"} 任务未完成，请重新提交。`);
          return;
        }
        if (payload.job.state === "queued" || payload.job.state === "processing") {
          setNotice(`已找回正在生成的 ${method === "wav2lip" ? "Wav2Lip" : method === "lipforcing" ? "Lip Forcing" : "MuseTalk"} 口型对齐，正在恢复进度。`);
          setBusy(true);
          try { await pollLocalTalking(endpoint, method, controller.signal); }
          finally { setBusy(false); }
        }
        if (payload.job.state === "ready_for_review" && (previewBeforeSave || method === "lipforcing" || apiRoot === "/api/user/avatars") && payload.job.variant?.video_url) {
          setPendingReview({ jobId: payload.job.id, sourceId: idle.avatar_action_id, sourceUrl: idle.video_url!, videoUrl: payload.job.variant.video_url, method });
          setPreview("talking");
          setNotice("口型对齐已生成，请预览后确认导入。");
        }
        if (payload.job.state === "success") {
          const record = await fetchOwnedAvatar(avatar.avatar_id, controller.signal);
          if (record) setActions(record.actions);
          setPreview("talking");
          setNotice(`已找回生成完成的 ${method === "wav2lip" ? "Wav2Lip" : method === "lipforcing" ? "Lip Forcing" : "MuseTalk"} 口型对齐。`);
        }
      }).catch(error => {
        if (!(error instanceof Error && error.name === "AbortError")) setNotice("暂时无法恢复讲话任务，请重新进入页面查询。");
      });
      return () => controller.abort();
    }

    if (draft.method === "minimax") {
      const recovered = readRecoverableGenerationTask(avatar.avatar_id, "talking");
      if (!recovered || recovered.provider !== "minimax" || recovered.sourceId !== idle.avatar_action_id || recovered.sourceUrl !== idle.video_url) return;
      setBusy(true);
      setNotice("已找回 MiniMax 讲话任务，正在恢复进度。");
      void resumeMiniMaxTalking(recovered.requestId, recovered.taskId, idle.avatar_action_id, idle.video_url, controller.signal)
        .catch(error => {
          if (!(error instanceof Error && error.name === "AbortError")) setNotice(error instanceof Error ? error.message : "讲话任务恢复失败");
        })
        .finally(() => setBusy(false));
      return () => controller.abort();
    }
  // generateTalking intentionally resumes only after the server confirms an existing job.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, avatar.avatar_id, draft.method, idle?.avatar_action_id, idle?.video_url, loaded, variant, previewBeforeSave]);

  function choosePairedAction(action: typeof available[number]) {
    const existing = action.talking_variants?.find(item => item.method === draft.method && !item.deleted_at && item.source_video_url === action.video_url)
      || action.talking_variants?.find(item => !item.deleted_at && item.source_video_url === action.video_url);
    if (!existing) return;
    setDraft({ ...selectIdle(draft, action.avatar_action_id), method: existing.method });
    setPreview("talking");
    setNotice("已切换到该底片的讲话版，素材选择已自动保存到本机。");
  }
  const previewUrl = preview === "idle" ? idle?.video_url : variant?.videoUrl;
  useEffect(() => {
    if (!floating || !active) return;
    onPreviewChange?.(previewUrl ? { url: previewUrl, name: avatar.display_name, kind: "talking" } : null);
  }, [active, avatar.display_name, floating, onPreviewChange, previewUrl]);

  async function resumeMiniMaxTalking(requestId: string, knownTaskId: string | undefined, sourceId: string, sourceUrl: string, signal: AbortSignal) {
    let taskId = knownTaskId;
    for (let attempt = 0; !taskId && attempt < 900; attempt++) {
      const response = await fetch(`/api/ltx/image-to-video?request_id=${encodeURIComponent(requestId)}`, { cache: "no-store", signal });
      const recovered = await response.json();
      if (!response.ok) throw new Error(recovered.error || "讲话任务恢复失败");
      if (recovered.submission_state === "submission_unknown") throw new Error(recovered.error || "任务提交结果无法确认，为避免重复扣费，系统不会自动重试。");
      if (typeof recovered.task_id === "string") {
        taskId = recovered.task_id;
        saveRecoverableGenerationTask({
          avatarId: avatar.avatar_id,
          purpose: "talking",
          requestId,
          provider: "minimax",
          taskId,
          sourceId,
          sourceUrl,
          startedAt: Date.now(),
        });
        break;
      }
      await abortableDelay(2_000, signal);
    }
    if (!taskId) throw new Error("任务提交确认超时；系统不会自动重复生成。");
    for (let attempt = 0; attempt < 300; attempt++) {
      await abortableDelay(3_000, signal);
      const result = await fetch(`/api/ltx/image-to-video/${encodeURIComponent(taskId)}`, { signal });
      const task = await result.json();
      if (!result.ok || task.state === "failed") throw new Error(task.error || "讲话生成失败");
      if (task.state === "success") {
        if (typeof task.result_url !== "string" || !/^\/api\/ltx\/image-to-video\/[^/]+\/result$/.test(task.result_url)) throw new Error("讲话视频地址无效");
        if (previewBeforeSave) {
          setDraft(current => current.idle === sourceId ? { ...current, variant: { sourceId, sourceUrl, videoUrl: task.result_url, method: "minimax" } } : current);
          setPreview("talking");
          setNotice("MiniMax 口型对齐已生成，请预览后确认导入。");
          return;
        }
        const saved = await fetch(`${apiRoot}/${encodeURIComponent(avatar.avatar_id)}/actions/${encodeURIComponent(sourceId)}/talking-variants/import-minimax`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ taskId }),
          signal,
        });
        const payload = await saved.json();
        if (!saved.ok || !payload.action) {
          setDraft(current => current.idle === sourceId ? { ...current, variant: { sourceId, sourceUrl, videoUrl: task.result_url, method: "minimax" } } : current);
          setPreview("talking");
          throw new Error(payload.error || "讲话版已生成，但保存到动作资产失败；刷新后可重试保存。");
        }
        setActions(current => current.map(item => item.avatar_action_id === sourceId ? payload.action : item));
        setDraft(current => current.idle === sourceId ? { ...current, variant: undefined } : current);
        clearRecoverableGenerationTask(avatar.avatar_id, "talking");
        setPreview("talking");
        setNotice("MiniMax 讲话版已保存到动作资产，请检查姿态与循环过渡。");
        return;
      }
    }
    throw new Error(`等待生成超时，任务 ${taskId} 可能仍在处理；刷新页面会继续查询，不会重复提交。`);
  }

  async function pollLocalTalking(endpoint: string, method: "musetalk" | "wav2lip" | "lipforcing", signal: AbortSignal) {
    for (let attempt = 0; attempt < 1200; attempt++) {
      const response = await fetch(endpoint, { cache: "no-store", signal });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "读取生成进度失败");
      if (payload.job?.state === "failed") throw new Error(payload.job.error || `${method} 生成失败`);
      if (payload.job?.state === "ready_for_review" && (previewBeforeSave || method === "lipforcing" || apiRoot === "/api/user/avatars") && payload.job.variant?.video_url) {
        setPendingReview({ jobId: payload.job.id, sourceId: payload.job.actionId, sourceUrl: payload.job.sourceUrl, videoUrl: payload.job.variant.video_url, method });
        setPreview("talking");
        setNotice("口型对齐已生成，请预览后确认导入。");
        return;
      }
      if (payload.job?.state === "success") {
        const record = await fetchOwnedAvatar(avatar.avatar_id, signal);
        if (record) setActions(record.actions);
        setPreview("talking");
        setNotice(`${method === "wav2lip" ? "Wav2Lip" : method === "lipforcing" ? "Lip Forcing" : "MuseTalk"} 口型对齐已保存，可在会话配置中选择。`);
        return;
      }
      if (!payload.job) throw new Error("任务状态丢失，请刷新动作库后重试。");
      setNotice(payload.job.state === "queued" ? "已排队，等待离线生成。" : `${method === "wav2lip" ? "Wav2Lip" : method === "lipforcing" ? "Lip Forcing" : "MuseTalk"} 正在生成口型对齐。`);
      await abortableDelay(3000, signal);
    }
    throw new Error("等待超时；生成任务可能仍在执行，重新进入页面可继续查询。");
  }

  async function generateTalking() {
    if (!idle?.video_url || generationLock.current) return;
    if (draft.method === "minimax") {
      try {
        if (!await ensureProviderKey("minimax")) return;
        const recovered = readRecoverableGenerationTask(avatar.avatar_id, "talking");
        if (recovered?.provider === "minimax" && recovered.sourceId === idle.avatar_action_id && recovered.sourceUrl === idle.video_url) {
          const controller = new AbortController();
          generationAbort.current = controller;
          setBusy(true);
          try {
            await resumeMiniMaxTalking(recovered.requestId, recovered.taskId, idle.avatar_action_id, idle.video_url, controller.signal);
          } finally { setBusy(false); }
          return;
        }
      } catch (cause) {
        setNotice(cause instanceof Error ? cause.message : "MiniMax 任务恢复失败");
        return;
      }
    }
    generationLock.current = true;
    const controller = new AbortController();
    generationAbort.current = controller;
    const sourceId = idle.avatar_action_id;
    const sourceUrl = idle.video_url;
    setBusy(true);
    setNotice("正在读取待机底片…");
    try {
      if (draft.method === "musetalk" || draft.method === "wav2lip" || draft.method === "lipforcing") {
        const method = draft.method;
        const endpoint = `${apiRoot}/${encodeURIComponent(avatar.avatar_id)}/actions/${encodeURIComponent(sourceId)}/talking-variants/${method === "wav2lip" ? "generate-wav2lip" : method === "lipforcing" ? "generate-lipforcing" : "generate"}`;
        let body: FormData | undefined;
        if (method === "wav2lip") {
          if (!wav2lipRights) throw new Error("请确认素材使用权及非商业用途");
          body = new FormData();
          if (wav2lipAudio) body.set("audio", wav2lipAudio);
          else body.set("audioSource", "builtin");
          body.set("rightsConfirmed", "true");
          body.set("usageScope", "internal_evaluation");
        }
        if (method === "lipforcing") {
          body = new FormData();
          const roleId = new URLSearchParams(window.location.search).get("return_to");
          if (roleId) body.set("roleId", roleId);
          if (lipForcingAudio) body.set("audio", lipForcingAudio);
          else if (floating && !roleId) body.set("audioSource", "builtin");
        }
        if (method === "musetalk" && (museTalkAudio || apiRoot === "/api/user/avatars")) {
          body = new FormData();
          if (museTalkAudio) body.set("audio", museTalkAudio);
        }
        const response = await fetch(`${endpoint}${previewBeforeSave ? "?preview=true" : ""}`, { method: "POST", body, signal: controller.signal });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || "讲话任务创建失败");
        if (!payload.job) throw new Error("任务创建后未返回状态");
        await pollLocalTalking(endpoint, method, controller.signal);
        return;
      }
      const source = await fetch(sourceUrl, { signal: controller.signal });
      if (!source.ok) throw new Error("待机视频读取失败");
      const blob = await source.blob();
      if (blob.size > 50 * 1024 * 1024) throw new Error("MiniMax 参考视频不能超过 50MB");
      if (!["video/mp4", "video/quicktime"].includes(blob.type)) throw new Error("MiniMax 参考底片需为 MP4 或 MOV，请选择兼容素材");
      const requestId = crypto.randomUUID();
      saveRecoverableGenerationTask({
        avatarId: avatar.avatar_id,
        purpose: "talking",
        requestId,
        provider: "minimax",
        sourceId,
        sourceUrl,
        startedAt: Date.now(),
      });
      const form = new FormData();
      form.set("avatarId", avatar.avatar_id);
      form.set("requestId", requestId);
      form.set("prompt", MINIMAX_TALKING_PROMPT);
      form.set("model", "MiniMax-H3");
      form.set("ratio", "adaptive");
      form.set("resolution", "768P");
      form.set("duration", String(duration));
      form.set("imageRole", "reference_image");
      form.set("creditsAccepted", "true");
      form.set("rightsConfirmed", "true");
      form.set("referenceVideo", new File([blob], blob.type === "video/quicktime" ? "idle.mov" : "idle.mp4", { type: blob.type }));
      const response = await fetch("/api/ltx/image-to-video", { method: "POST", body: form, signal: controller.signal });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "讲话生成任务创建失败");
      if (payload.submission_state === "submission_unknown") throw new Error(payload.error || "任务提交结果无法确认，为避免重复扣费，系统不会自动重试。");
      setNotice("MiniMax 正在基于待机底片生成讲话版；刷新页面后会自动恢复。");
      await resumeMiniMaxTalking(requestId, typeof payload.task_id === "string" ? payload.task_id : undefined, sourceId, sourceUrl, controller.signal);
    } catch (error) {
      if (!(error instanceof Error && error.name === "AbortError")) setNotice(error instanceof Error ? error.message : "讲话生成失败");
    } finally { generationLock.current = false; setBusy(false); }
  }
  async function acceptPreview() {
    if (!idle || busy) return;
    const review = currentReview;
    const miniMaxTask = draft.method === "minimax" && generatedVariant?.method === "minimax"
      ? readRecoverableGenerationTask(avatar.avatar_id, "talking") : null;
    if (!review && (!miniMaxTask?.taskId || miniMaxTask.sourceId !== idle.avatar_action_id || miniMaxTask.sourceUrl !== idle.video_url)) return;
    setBusy(true);
    try {
      const root = `${apiRoot}/${encodeURIComponent(avatar.avatar_id)}/actions/${encodeURIComponent(idle.avatar_action_id)}/talking-variants`;
      const response = await fetch(`${root}/${review ? "accept" : "import-minimax"}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(review ? { jobId: review.jobId } : { taskId: miniMaxTask?.taskId }),
      });
      const payload = await response.json();
      if (!response.ok || !payload.action) throw new Error(payload.error || "导入口型对齐失败");
      setActions(current => current.map(item => item.avatar_action_id === idle.avatar_action_id ? payload.action : item));
      if (review) setPendingReview(null);
      else {
        setDraft(current => ({ ...current, variant: undefined }));
        clearRecoverableGenerationTask(avatar.avatar_id, "talking");
      }
      setNotice("口型对齐已导入动作资产，可在会话配置中选择。");
      const savedVideoUrl = review?.videoUrl ?? generatedVariant?.videoUrl;
      const savedVariant = payload.action.talking_variants?.find((item: { id: string; video_url: string }) => item.video_url === savedVideoUrl);
      onSaved?.(savedVariant?.id);
    } catch (error) { setNotice(error instanceof Error ? error.message : "导入口型对齐失败"); }
    finally { setBusy(false); }
  }
  function save() {
    try { localStorage.setItem(key, JSON.stringify(draft)); setNotice("素材草稿已保存到当前浏览器，尚未启用会话播放。"); }
    catch { setNotice("草稿保存失败，请检查浏览器存储权限。"); }
  }
  const configuration = <aside className={`${styles.taskSidebar} ${floating ? styles.floatingChoreography : ""}`}>
        {header}
        <section className={`${styles.capabilityModule} ${styles.lightweightModule}`}>
          <div className={styles.lightweightIdentity}><Image src={avatar.source_image_url} alt="" width={40} height={40} unoptimized /><div><strong>{avatar.display_name}</strong><small>{floating ? idle ? `已选动作 · ${idle.display_name}` : "所选动作不可用" : "当前数字人 · 动作配对"}</small></div></div>
          {!floating ? <section className={styles.lightweightGroup} aria-label="动作编排">
          <div className={styles.lightweightGroupHeading}><h3>动作编排 · 待机底片</h3>{onCreateAction ? <button type="button" disabled={busy} onClick={onCreateAction}>＋ 新建动作</button> : null}</div>
          <div className={styles.lightweightField}>
            <SelectMenu value={idle ? draft.idle : ""} ariaLabel="待机动作 · 从资产库选择" compact disabled={!loaded || busy}
              options={[{ value: "", label: draft.idle && !idle ? "原素材不可用，请重新选择" : "从资产库选择待机动作" }, ...available.map(action => ({ value: action.avatar_action_id, label: action.display_name, description: action.talking_variants?.some(item => !item.deleted_at && item.source_video_url === action.video_url) ? "已有配对讲话版" : undefined }))]}
              onChange={value => { setDraft(selectIdle(draft, value)); setPreview("idle"); setNotice("待机底片已更换，已带出该底片已有的讲话版；缺少时可重新生成。"); }} />
          </div>
          </section> : null}
          <section className={styles.lightweightGroup} aria-label="生成口型素材">
          <h3>{floating ? "口型对齐模型" : "生成口型素材"}</h3>
          <div className={styles.lightweightField}>
            <SelectMenu value={draft.method} ariaLabel={floating ? "口型对齐模型" : "配对口型对齐"} compact placement={floating ? "top" : "bottom"} disabled={!loaded || busy}
              options={(floating ? ["lipforcing", "musetalk", "wav2lip"] as const : ["lipforcing", "musetalk", "minimax", "wav2lip"] as const).map(method => {
                const saved = idle?.talking_variants?.find(item => item.method === method && !item.deleted_at && item.source_video_url === idle.video_url);
                const generated = generatedVariant?.method === method;
                const modelLabel = method === "lipforcing" ? "Lip Forcing" : method === "musetalk" ? "MuseTalk 1.5" : method === "minimax" ? "MiniMax · 视频参考" : "Wav2Lip";
                return { value: method, label: floating ? modelLabel : generated ? "MiniMax · 新生成的讲话版" : saved?.display_name || (method === "lipforcing" ? "Lip Forcing · 离线口型对齐" : method === "musetalk" ? "MuseTalk 1.5 · GPU 口型" : method === "minimax" ? "MiniMax · 视频参考" : "Wav2Lip · 离线口型"), description: generated || saved ? "当前底片的配对素材" : "此底片尚未生成" };
              })}
              onChange={method => {
                setDraft({ ...draft, method: method as TalkingMethod });
                const exists = generatedVariant?.method === method || idle?.talking_variants?.some(item => item.method === method && !item.deleted_at && item.source_video_url === idle.video_url);
                setPreview(exists ? "talking" : "idle");
              }} />
          </div>
          {variant ? <div className={styles.lightweightMaterialStatus}><span>{currentReview || (previewBeforeSave && generatedVariant?.method === "minimax") ? "待确认导入" : "已配对 · 过渡待验证"}</span><button type="button" className={styles.lightweightButton} onClick={() => setPreview("talking")}>预览</button></div> : !floating ? <p className={styles.lightweightHint}>此底片尚无当前方式的口型对齐。</p> : null}
          {(previewBeforeSave || draft.method === "lipforcing" || apiRoot === "/api/user/avatars") && (currentReview || (generatedVariant?.method === "minimax" && readRecoverableGenerationTask(avatar.avatar_id, "talking")?.taskId)) && <button type="button" className={styles.lightweightButton} disabled={busy} onClick={() => void acceptPreview()}>确认导入口型对齐</button>}
          {floating ? <div className={styles.floatingAudioOptions}>
            <span>音频 · {draft.method === "wav2lip" && wav2lipAudio ? wav2lipAudio.name : draft.method === "lipforcing" && lipForcingAudio ? lipForcingAudio.name : draft.method === "musetalk" && museTalkAudio ? museTalkAudio.name : "内置参考音频"}</span>
            <details><summary>上传音频（可选）</summary><input aria-label="上传参考音频" type="file" accept=".wav,.mp3,.m4a,audio/wav,audio/mpeg,audio/mp4" disabled={busy} onChange={event => draft.method === "wav2lip" ? setWav2lipAudio(event.target.files?.[0] || null) : draft.method === "lipforcing" ? setLipForcingAudio(event.target.files?.[0] || null) : setMuseTalkAudio(event.target.files?.[0] || null)} /></details>
          </div> : null}
          {floating && draft.method === "wav2lip" ? <label className={styles.floatingRights}><input type="checkbox" checked={wav2lipRights} disabled={busy} onChange={event => setWav2lipRights(event.target.checked)} />确认素材使用权，仅用于非商业内部评估</label> : null}
          {floating ? <button type="button" className={`${styles.lightweightButton} ${styles.floatingGenerateButton}`} disabled={!idle || busy || (draft.method === "wav2lip" && !wav2lipRights)} onClick={() => void generateTalking()}>{busy ? "正在生成…" : variant ? "重新生成口型动作" : "生成口型动作"}</button> : <details className={styles.lightweightGeneration} open={!variant} key={`${draft.method}-${Boolean(variant)}`}><summary>{draft.method === "lipforcing" ? "Lip Forcing 口型对齐" : variant ? draft.method === "musetalk" ? "MuseTalk 口型对齐" : "重新生成讲话版" : "生成讲话版"}</summary>
          {draft.method === "lipforcing" ? <><p>使用当前角色声音自动生成参考讲话音频，完成后先预览再保存。也可以上传自己的参考音频。</p><label className={styles.lightweightField}>替换参考音频（可选，≤ 20MB）<input type="file" accept=".wav,.mp3,.m4a,audio/wav,audio/mpeg,audio/mp4" disabled={busy} onChange={event => setLipForcingAudio(event.target.files?.[0] || null)} /></label></> : draft.method === "musetalk" ? <p>用当前动作生成配对口型对齐，完成后{previewBeforeSave ? "先预览再导入" : "自动保存"}。会话中循环播放讲话动作，不逐字对齐新回复。</p> : draft.method === "minimax" ? <>
            <div className={styles.lightweightField}><span>生成时长（与底片一致）</span><SelectMenu value={String(duration)} ariaLabel="生成时长" compact disabled={busy} options={Array.from({ length: 12 }, (_, index) => ({ value: String(index + 4), label: `${index + 4} 秒` }))} onChange={value => setDuration(Number(value))} /></div>
            <details><summary>查看 MiniMax 讲话提示词</summary><p>{MINIMAX_TALKING_PROMPT}</p><p>提示词只约束生成；局部嘴部合成是独立后处理，当前生成按钮不会自动执行。</p></details>
            <p>使用 MiniMax H3 / 768P。点击生成会上传当前底片并消耗 API 额度；请确认拥有素材使用权。</p>
          </> : <><p className={styles.lightweightNotice}>用当前底片和参考讲话音频离线生成口型素材。标准 Wav2Lip 仅限个人、研究或内部评估等非商业用途。</p><label className={styles.lightweightField}>参考讲话音频（WAV、MP3、M4A，≤ 20MB）<input type="file" accept=".wav,.mp3,.m4a,audio/wav,audio/mpeg,audio/mp4" disabled={busy} onChange={event => setWav2lipAudio(event.target.files?.[0] || null)} /></label><label className={styles.lightweightField}><input type="checkbox" checked={wav2lipRights} disabled={busy} onChange={event => setWav2lipRights(event.target.checked)} />我确认拥有人物、底片和音频的使用权，并仅用于非商业内部评估</label></>}
          <button type="button" className={styles.lightweightButton} disabled={!idle || busy || (!floating && (draft.method === "musetalk" || draft.method === "wav2lip" || draft.method === "lipforcing") && Boolean(variant)) || (draft.method === "wav2lip" && (!wav2lipAudio || !wav2lipRights))} onClick={() => void generateTalking()}>{busy ? "正在生成口型对齐…" : floating ? variant ? "重新生成口型动作" : "生成口型动作" : draft.method === "lipforcing" ? variant ? "已保存 Lip Forcing 口型对齐" : "生成 Lip Forcing 口型对齐" : draft.method === "musetalk" ? variant ? "已生成 MuseTalk 口型对齐" : "生成 MuseTalk 口型对齐" : draft.method === "wav2lip" ? variant ? "已生成 Wav2Lip 口型对齐" : "生成 Wav2Lip 口型对齐" : "基于待机生成讲话版"}</button>
          </details>}
          </section>
          {!floating ? <><details className={styles.lightweightHelp}><summary>使用说明与能力范围</summary><p>讲话版附属于当前底片，不加入普通动作列表。切换底片时会带出它自己的讲话版。</p><p>会话配置可直接选择已保存的口型对齐，自动配对待机动作。MiniMax 视频参考不保证逐帧一致。</p></details>
          <div className={styles.lightweightSave}>
          <button type="button" className={styles.lightweightButton} disabled={!loaded || !idle || busy} onClick={save}>保存本机素材草稿</button>
          </div></> : null}
          <p role="status">{notice}</p>
          {draft.method === "minimax" && notice.includes("API Key") && <button className={styles.lightweightButton} type="button" onClick={() => void ensureProviderKey("minimax", true).catch((cause: unknown) => setNotice(cause instanceof Error ? cause.message : "无法更换 MiniMax Key"))}>更换 MiniMax Key</button>}
        </section>
      </aside>;
  return <>
    {floating ? configuration : <StudioConfigOverlay open={open} onOpenChange={onOpenChange} label="口型动作编排" icon={<Film />}>{configuration}</StudioConfigOverlay>}
    {!floating ? <section className={`${styles.visualStage} ${styles.lightweightStage}`} aria-label="轻量动作素材预览">
      <header className={`${actionStyles.previewModeSwitch} ${styles.floatingPreviewSwitch}`}>
        <button type="button" aria-pressed={preview === "idle"} data-active={preview === "idle"} onClick={() => setPreview("idle")}>待机素材</button>
        <button type="button" aria-pressed={preview === "talking"} data-active={preview === "talking"} disabled={!variant} aria-describedby={!variant ? "talking-preview-unavailable" : undefined} onClick={() => setPreview("talking")}>口型对齐</button>
      </header>
      {!variant ? <div id="talking-preview-unavailable" className={styles.talkingUnavailable}>
        <p>{idle ? `“${idle.display_name}”尚无${draft.method === "lipforcing" ? " Lip Forcing" : draft.method === "musetalk" ? " MuseTalk" : draft.method === "minimax" ? " MiniMax" : " Wav2Lip"}讲话版。请生成该底片的讲话版，或选择已有配对的动作。` : "请先选择待机动作，才能预览它的讲话版。"}</p>
        {pairedActions.map(action => <button type="button" key={action.avatar_action_id} disabled={busy} onClick={() => choosePairedAction(action)}>查看{action.display_name}的讲话版</button>)}
      </div> : null}
      <div className={styles.visualStageBody}>
        {active && previewUrl ? <video ref={video} key={previewUrl} className={styles.stageVideo} src={previewUrl} poster={avatar.source_image_url} autoPlay controls muted loop playsInline preload="metadata" />
          : <Image src={avatar.source_image_url} alt={avatar.display_name} fill sizes="(max-width: 900px) 100vw, 70vw" unoptimized style={{ objectFit: "contain" }} />}
      </div>
    </section> : null}
  </>;
}

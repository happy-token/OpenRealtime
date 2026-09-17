"use client";

import Image from "next/image";
import { SelectMenu } from "@/components/ui/select-menu";
import { MINIMAX_TALKING_PROMPT } from "@/lib/minimax-talking-prompt";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Film } from "lucide-react";
import { fetchOwnedAvatar } from "@/lib/avatar-catalog-client";
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

export function AvatarLightweightConfig({ avatar, header, active, open, onOpenChange, onCreateAction }: {
  avatar: OwnedAvatarRecord; header: ReactNode; active: boolean;
  open: boolean; onOpenChange: (open: boolean) => void; onCreateAction: () => void;
}) {
  const [actions, setActions] = useState(avatar.actions);
  const [draft, setDraft] = useState<LightweightDraft>({ idle: "", method: "musetalk" });
  const [preview, setPreview] = useState<"idle" | "talking">("idle");
  const [notice, setNotice] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [duration, setDuration] = useState(10);
  const generationLock = useRef(false);
  const generationAbort = useRef<AbortController | null>(null);
  const recoveryAttempt = useRef("");
  useEffect(() => () => generationAbort.current?.abort(), []);
  const video = useRef<HTMLVideoElement>(null);
  const key = `openrealtime:lightweight-draft:${avatar.avatar_id}`;
  useEffect(() => {
    try {
      const raw: unknown = JSON.parse(localStorage.getItem(key) || "null");
      setDraft(readLightweightDraft(raw));
    } catch { setNotice("无法读取本机草稿，请重新选择素材。"); }
    setLoaded(true);
  }, [key]);
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
  const attachedVariant = idle?.talking_variants?.find(item => item.method === draft.method && item.source_video_url === idle.video_url);
  const generatedVariant = matchingVariant(draft, idle?.video_url);
  const variant = generatedVariant?.method === draft.method ? generatedVariant : attachedVariant ? { videoUrl: attachedVariant.video_url } : undefined;
  const pairedActions = available.filter(action => action.talking_variants?.some(item => item.source_video_url === action.video_url));
  useEffect(() => {
    if (!active || !loaded || !idle?.video_url || variant || busy) return;
    const recoveryKey = `${draft.method}:${idle.avatar_action_id}:${idle.video_url}`;
    if (recoveryAttempt.current === recoveryKey) return;
    recoveryAttempt.current = recoveryKey;
    const controller = new AbortController();
    generationAbort.current = controller;

    if (draft.method === "musetalk") {
      const endpoint = `/api/avatars/${encodeURIComponent(avatar.avatar_id)}/actions/${encodeURIComponent(idle.avatar_action_id)}/talking-variants/generate`;
      void fetch(endpoint, { cache: "no-store", signal: controller.signal }).then(async response => {
        const payload = await response.json();
        if (!response.ok || !payload.job) return;
        if (payload.job.state === "failed") {
          setNotice(payload.job.error || "上次 MuseTalk 任务未完成，请先核对任务状态。");
          return;
        }
        if (payload.job.state === "queued" || payload.job.state === "processing") {
          setNotice("已找回正在生成的 MuseTalk 讲话素材，正在恢复进度。");
          await generateTalking();
        }
        if (payload.job.state === "success") {
          const record = await fetchOwnedAvatar(avatar.avatar_id, controller.signal);
          if (record) setActions(record.actions);
          setPreview("talking");
          setNotice("已找回生成完成的 MuseTalk 讲话素材。");
        }
      }).catch(error => {
        if (!(error instanceof Error && error.name === "AbortError")) setNotice("暂时无法恢复 MuseTalk 任务，系统不会自动重复生成。");
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
  }, [active, avatar.avatar_id, draft.method, idle?.avatar_action_id, idle?.video_url, loaded, variant]);

  function choosePairedAction(action: typeof available[number]) {
    const existing = action.talking_variants?.find(item => item.method === draft.method && item.source_video_url === action.video_url)
      || action.talking_variants?.find(item => item.source_video_url === action.video_url);
    if (!existing) return;
    setDraft({ ...selectIdle(draft, action.avatar_action_id), method: existing.method });
    setPreview("talking");
    setNotice("已切换到该底片的讲话版，素材选择已自动保存到本机。");
  }
  const previewUrl = preview === "idle" ? idle?.video_url : variant?.videoUrl;

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
        setDraft(current => current.idle === sourceId ? { ...current, variant: { sourceId, sourceUrl, videoUrl: task.result_url, method: "minimax" } } : current);
        setPreview("talking");
        clearRecoverableGenerationTask(avatar.avatar_id, "talking");
        setNotice("讲话版已生成，请检查同相位姿态与循环过渡。生成结果不代表逐帧一致。");
        return;
      }
    }
    throw new Error(`等待生成超时，任务 ${taskId} 可能仍在处理；刷新页面会继续查询，不会重复提交。`);
  }

  async function generateTalking() {
    if (!idle?.video_url || draft.method === "wav2lip" || draft.method === "lipforcing" || generationLock.current) return;
    generationLock.current = true;
    const controller = new AbortController();
    generationAbort.current = controller;
    const sourceId = idle.avatar_action_id;
    const sourceUrl = idle.video_url;
    setBusy(true);
    setNotice("正在读取待机底片…");
    try {
      if (draft.method === "musetalk") {
        const endpoint = `/api/avatars/${encodeURIComponent(avatar.avatar_id)}/actions/${encodeURIComponent(sourceId)}/talking-variants/generate`;
        const response = await fetch(endpoint, { method: "POST", signal: controller.signal });
        let payload = await response.json();
        if (!response.ok) throw new Error(payload.error || "讲话任务创建失败");
        for (let attempt = 0; attempt < 1200; attempt++) {
          if (payload.job?.state === "failed") throw new Error(payload.job.error || "MuseTalk 生成失败");
          if (payload.job?.state === "success") {
            const record = await fetchOwnedAvatar(avatar.avatar_id, controller.signal);
            if (record) setActions(record.actions);
            setPreview("talking");
            setNotice("MuseTalk 讲话素材已保存，可在会话配置中直接选择。");
            return;
          }
          if (!payload.job) throw new Error("任务进程已重启，请刷新动作库；若素材未生成，请重试。");
          setNotice(payload.job.state === "queued" ? "已排队，等待 GPU 生成讲话素材。" : "MuseTalk 正在生成讲话素材，完成后自动保存到动作库。");
          await new Promise<void>((resolve, reject) => {
            const cancel = () => { clearTimeout(timer); reject(new DOMException("Cancelled", "AbortError")); };
            const timer = setTimeout(() => { controller.signal.removeEventListener("abort", cancel); resolve(); }, 3000);
            controller.signal.addEventListener("abort", cancel, { once: true });
            if (controller.signal.aborted) cancel();
          });
          const status = await fetch(endpoint, { signal: controller.signal });
          payload = await status.json();
          if (!status.ok) throw new Error(payload.error || "读取生成进度失败");
        }
        throw new Error("等待超时；GPU 任务可能仍在执行，重新点击可查询同一任务。");
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
  function save() {
    try { localStorage.setItem(key, JSON.stringify(draft)); setNotice("素材草稿已保存到当前浏览器，尚未启用会话播放。"); }
    catch { setNotice("草稿保存失败，请检查浏览器存储权限。"); }
  }
  return <>
    <StudioConfigOverlay open={open} onOpenChange={onOpenChange} label="轻量动作配置" icon={<Film />}>
      <aside className={styles.taskSidebar}>
        {header}
        <section className={`${styles.capabilityModule} ${styles.lightweightModule}`}>
          <div className={styles.lightweightIdentity}><Image src={avatar.source_image_url} alt="" width={40} height={40} unoptimized /><div><strong>{avatar.display_name}</strong><small>当前数字人 · 动作配对</small></div></div>
          <section className={styles.lightweightGroup} aria-label="基础动作">
          <div className={styles.lightweightGroupHeading}><h3>待机底片</h3><button type="button" disabled={busy} onClick={onCreateAction}>＋ 新建动作</button></div>
          <div className={styles.lightweightField}>
            <SelectMenu value={idle ? draft.idle : ""} ariaLabel="待机动作 · 从资产库选择" compact disabled={!loaded || busy}
              options={[{ value: "", label: draft.idle && !idle ? "原素材不可用，请重新选择" : "从资产库选择待机动作" }, ...available.map(action => ({ value: action.avatar_action_id, label: action.display_name, description: action.talking_variants?.some(item => item.source_video_url === action.video_url) ? "已有配对讲话版" : undefined }))]}
              onChange={value => { setDraft(selectIdle(draft, value)); setPreview("idle"); setNotice("待机底片已更换，已带出该底片已有的讲话版；缺少时可重新生成。"); }} />
          </div>
          </section>
          <section className={styles.lightweightGroup} aria-label="生成讲话素材">
          <h3>生成讲话素材</h3>
          <div className={styles.lightweightField}>
            <SelectMenu value={draft.method} ariaLabel="配对讲话素材" compact disabled={!loaded || busy}
              options={(["lipforcing", "musetalk", "minimax", "wav2lip"] as const).map(method => {
                const saved = idle?.talking_variants?.find(item => item.method === method && item.source_video_url === idle.video_url);
                const generated = generatedVariant?.method === method;
                return { value: method, label: generated ? "MiniMax · 新生成的讲话版" : saved?.display_name || (method === "lipforcing" ? "Lip Forcing · 离线讲话素材" : method === "musetalk" ? "MuseTalk 1.5 · GPU 口型" : method === "minimax" ? "MiniMax · 视频参考" : "Wav2Lip · 已有素材"), description: generated || saved ? "当前底片的配对素材" : "此底片尚未生成" };
              })}
              onChange={method => {
                setDraft({ ...draft, method: method as TalkingMethod });
                const exists = generatedVariant?.method === method || idle?.talking_variants?.some(item => item.method === method && item.source_video_url === idle.video_url);
                setPreview(exists ? "talking" : "idle");
              }} />
          </div>
          {variant ? <div className={styles.lightweightMaterialStatus}><span>已配对 · 过渡待验证</span><button type="button" className={styles.lightweightButton} onClick={() => setPreview("talking")}>预览</button></div> : <p className={styles.lightweightHint}>此底片尚无当前方式的讲话素材。</p>}
          <details className={styles.lightweightGeneration} open={!variant} key={`${draft.method}-${Boolean(variant)}`}><summary>{draft.method === "lipforcing" ? "Lip Forcing 讲话素材" : variant ? draft.method === "musetalk" ? "MuseTalk 讲话素材" : "重新生成讲话版" : "生成讲话版"}</summary>
          {draft.method === "lipforcing" ? <p>使用已生成并保存的 Lip Forcing 讲话素材，可在会话配置中选择。</p> : draft.method === "musetalk" ? <p>用当前动作生成配对讲话素材，完成后自动保存。会话中循环播放讲话动作，不逐字对齐新回复。</p> : draft.method === "minimax" ? <>
            <div className={styles.lightweightField}><span>生成时长（与底片一致）</span><SelectMenu value={String(duration)} ariaLabel="生成时长" compact disabled={busy} options={Array.from({ length: 12 }, (_, index) => ({ value: String(index + 4), label: `${index + 4} 秒` }))} onChange={value => setDuration(Number(value))} /></div>
            <details><summary>查看 MiniMax 讲话提示词</summary><p>{MINIMAX_TALKING_PROMPT}</p><p>提示词只约束生成；局部嘴部合成是独立后处理，当前生成按钮不会自动执行。</p></details>
            <p>使用 MiniMax H3 / 768P。点击生成会上传当前底片并消耗 API 额度；请确认拥有素材使用权。</p>
          </> : <p className={styles.lightweightNotice}>使用同一底片和参考讲话音频离线处理，优先逐帧推理与嘴部融合质量。Wav2Lip 离线任务接口尚未接入，暂不能从页面启动。</p>}
          <button type="button" className={styles.lightweightButton} disabled={!idle || busy || draft.method === "wav2lip" || draft.method === "lipforcing" || (draft.method === "musetalk" && Boolean(variant))} onClick={() => void generateTalking()}>{busy ? "正在生成讲话素材…" : draft.method === "lipforcing" ? variant ? "已保存 Lip Forcing 讲话素材" : "等待离线素材生成" : draft.method === "musetalk" ? variant ? "已生成 MuseTalk 讲话素材" : "生成 MuseTalk 讲话素材" : "基于待机生成讲话版"}</button>
          </details>
          </section>
          <details className={styles.lightweightHelp}><summary>使用说明与能力范围</summary><p>讲话版附属于当前底片，不加入普通动作列表。切换底片时会带出它自己的讲话版。</p><p>会话配置可直接选择已保存的讲话素材，自动配对待机动作。MiniMax 视频参考不保证逐帧一致。</p></details>
          <div className={styles.lightweightSave}>
          <button type="button" className={styles.lightweightButton} disabled={!loaded || !idle || busy} onClick={save}>保存本机素材草稿</button>
          </div>
          <p role="status">{notice}</p>
        </section>
      </aside>
    </StudioConfigOverlay>
    <section className={`${styles.visualStage} ${styles.lightweightStage}`} aria-label="轻量动作素材预览">
      <header className={`${actionStyles.previewModeSwitch} ${styles.floatingPreviewSwitch}`}>
        <button type="button" aria-pressed={preview === "idle"} data-active={preview === "idle"} onClick={() => setPreview("idle")}>待机素材</button>
        <button type="button" aria-pressed={preview === "talking"} data-active={preview === "talking"} disabled={!variant} aria-describedby={!variant ? "talking-preview-unavailable" : undefined} onClick={() => setPreview("talking")}>讲话素材</button>
      </header>
      {!variant ? <div id="talking-preview-unavailable" className={styles.talkingUnavailable}>
        <p>{idle ? `“${idle.display_name}”尚无${draft.method === "lipforcing" ? " Lip Forcing" : draft.method === "musetalk" ? " MuseTalk" : draft.method === "minimax" ? " MiniMax" : " Wav2Lip"}讲话版。请生成该底片的讲话版，或选择已有配对的动作。` : "请先选择待机动作，才能预览它的讲话版。"}</p>
        {pairedActions.map(action => <button type="button" key={action.avatar_action_id} disabled={busy} onClick={() => choosePairedAction(action)}>查看{action.display_name}的讲话版</button>)}
      </div> : null}
      <div className={styles.visualStageBody}>
        {active && previewUrl ? <video ref={video} key={previewUrl} className={styles.stageVideo} src={previewUrl} poster={avatar.source_image_url} autoPlay controls muted loop playsInline preload="metadata" />
          : <Image src={avatar.source_image_url} alt={avatar.display_name} fill sizes="(max-width: 900px) 100vw, 70vw" unoptimized style={{ objectFit: "contain" }} />}
      </div>
    </section>
  </>;
}

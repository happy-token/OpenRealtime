"use client";
import { SelectMenu } from "@/components/ui/select-menu";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import type { OwnedAvatarActionRecord } from "@/lib/avatar-records";
import { saveGeneratedPersonalAction } from "@/lib/personal-action-client";
import styles from "./production-service-screen.module.css";

const TASK_KEY = "openrealtime:personal-minimax-task";
type Status = { ready?: boolean; configured?: boolean; enabled?: boolean; error?: string; task_id?: string; state?: string; submission_state?: string; result_url?: string };
type MotionAsset = { id: string; taskId: string; prompt: string; duration: number; createdAt: string };
type PersonalAvatar = { avatar_id: string; display_name: string; source_image_url?: string; actions: { video_url: string | null }[] };

async function readStatus(response: Response): Promise<Status> {
  const payload = await response.json() as Status;
  if (!response.ok) throw new Error(payload.error || "视频生成服务暂时不可用");
  return payload;
}

export function PersonalVideoGeneration({
  initialAvatarId,
  returnToRoleId,
  embedded = false,
  onActionSaved,
  onPreviewChange,
}: {
  initialAvatarId?: string;
  returnToRoleId?: string;
  embedded?: boolean;
  onActionSaved?: (action: OwnedAvatarActionRecord) => void;
  onPreviewChange?: (url: string) => void;
} = {}) {
  const router = useRouter();
  const [available, setAvailable] = useState(false);
  const [signedOut, setSignedOut] = useState(false);
  const [ready, setReady] = useState(false);
  const [configured, setConfigured] = useState(false);
  const [image, setImage] = useState<File | null>(null);
  const [prompt, setPrompt] = useState("");
  const [duration, setDuration] = useState(4);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [resultUrl, setResultUrl] = useState("");
  const [finishedTaskId, setFinishedTaskId] = useState("");
  const [assets, setAssets] = useState<MotionAsset[]>([]);
  const [personalAvatars, setPersonalAvatars] = useState<PersonalAvatar[]>([]);
  const [avatarName, setAvatarName] = useState("");
  const [avatarImage, setAvatarImage] = useState<File | null>(null);
  const [selectedAvatarId, setSelectedAvatarId] = useState("");
  const controller = useRef<AbortController | null>(null);
  const taskStorageKey = embedded && initialAvatarId ? `${TASK_KEY}:${initialAvatarId}` : TASK_KEY;

  useEffect(() => {
    onPreviewChange?.(resultUrl);
  }, [onPreviewChange, resultUrl]);

  useEffect(() => {
    const session = new AbortController();
    void fetch("/api/user/video-generation", { cache: "no-store", signal: session.signal }).then(async response => {
      if (response.status === 401) { setSignedOut(true); return; }
      const status = await readStatus(response);
      setAvailable(true);
      setReady(Boolean(status.ready));
      setConfigured(Boolean(status.configured));
      const libraryResponse = await fetch("/api/user/motion-assets", { cache: "no-store", signal: session.signal });
      if (libraryResponse.ok) setAssets(((await libraryResponse.json()) as { assets: MotionAsset[] }).assets);
      const avatarResponse = await fetch("/api/user/avatars", { cache: "no-store", signal: session.signal });
      if (avatarResponse.ok) {
        const avatars = ((await avatarResponse.json()) as { avatars: PersonalAvatar[] }).avatars;
        setPersonalAvatars(avatars);
        const selected = avatars.find(avatar => avatar.avatar_id === initialAvatarId) ?? avatars[0];
        setSelectedAvatarId(selected?.avatar_id || "");
        if (initialAvatarId && selected?.source_image_url) {
          const imageResponse = await fetch(selected.source_image_url, { cache: "no-store", signal: session.signal });
          if (imageResponse.ok) {
            const blob = await imageResponse.blob();
            setImage(new File([blob], `${selected.display_name}.png`, { type: blob.type || "image/png" }));
          }
        }
      }
      const saved = localStorage.getItem(taskStorageKey);
      if (saved && /^[0-9a-f-]{36}$/i.test(saved)) {
        setBusy(true);
        await resume(saved, session.signal).finally(() => setBusy(false));
      }
    }).catch(error => {
      if (!(error instanceof Error && error.name === "AbortError")) setNotice(error instanceof Error ? error.message : "视频生成状态读取失败");
    });
    return () => { session.abort(); controller.current?.abort(); };
  // Resume uses the current API contract and is intentionally called only once per mount.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialAvatarId, taskStorageKey]);

  async function waitForTask(taskId: string, signal: AbortSignal) {
    for (let index = 0; index < 600; index++) {
      const status = await readStatus(await fetch(`/api/user/video-generation/${encodeURIComponent(taskId)}`, { cache: "no-store", signal }));
      if (status.state === "failed") throw new Error(status.error || "MiniMax 视频生成失败");
      if (status.state === "success" && status.result_url) {
        setResultUrl(status.result_url);
        setFinishedTaskId(taskId);
        setNotice("视频已生成，可以下载。任务记录会保留一周。");
        return;
      }
      setNotice("MiniMax 正在生成视频，刷新页面后会继续查询同一任务。");
      await new Promise<void>((resolve, reject) => {
        const cancel = () => { clearTimeout(timer); reject(new DOMException("Cancelled", "AbortError")); };
        const timer = setTimeout(() => { signal.removeEventListener("abort", cancel); resolve(); }, 3_000);
        signal.addEventListener("abort", cancel, { once: true });
        if (signal.aborted) cancel();
      });
    }
    throw new Error("等待超时；任务可能仍在生成，刷新页面可继续查询。");
  }

  async function resume(requestId: string, signal: AbortSignal) {
    for (let index = 0; index < 30; index++) {
      const response = await fetch(`/api/user/video-generation?request_id=${encodeURIComponent(requestId)}`, { cache: "no-store", signal });
      if (response.status === 404) { localStorage.removeItem(taskStorageKey); return; }
      const status = await readStatus(response);
      if (status.submission_state === "submission_unknown") throw new Error(status.error || "付费任务提交结果无法确认，请先核对服务商记录。");
      if (status.task_id) { await waitForTask(status.task_id, signal); return; }
      await new Promise(resolve => setTimeout(resolve, 2_000));
    }
    throw new Error("付费任务仍在提交，请稍后刷新页面查询。");
  }

  async function submit() {
    if (!image || !confirmed || busy) return;
    const requestId = crypto.randomUUID();
    const current = new AbortController();
    controller.current = current;
    setBusy(true);
    setResultUrl("");
    setFinishedTaskId("");
    setNotice("正在提交 MiniMax 任务…");
    localStorage.setItem(taskStorageKey, requestId);
    try {
      const form = new FormData();
      form.set("image", image);
      form.set("prompt", prompt);
      form.set("duration", String(duration));
      form.set("requestId", requestId);
      form.set("creditsAccepted", "true");
      form.set("rightsConfirmed", "true");
      const status = await readStatus(await fetch("/api/user/video-generation", { method: "POST", body: form, signal: current.signal }));
      if (status.submission_state === "submission_unknown") throw new Error(status.error || "提交结果无法确认，请核对 MiniMax 任务记录。");
      if (status.task_id) await waitForTask(status.task_id, current.signal);
      else await resume(requestId, current.signal);
    } catch (error) {
      if (!(error instanceof Error && error.name === "AbortError")) setNotice(error instanceof Error ? error.message : "视频生成失败");
    } finally { setBusy(false); }
  }

  async function saveToLibrary() {
    if (!finishedTaskId || busy) return;
    setBusy(true);
    try {
      const response = await fetch("/api/user/motion-assets", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ taskId: finishedTaskId }) });
      const payload = await response.json() as { asset?: MotionAsset; error?: string };
      if (!response.ok || !payload.asset) throw new Error(payload.error || "保存动作素材失败");
      const saved = payload.asset;
      setAssets(current => [saved, ...current.filter(asset => asset.id !== saved.id)]);
      setNotice("视频已保存到个人动作素材库。");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "保存动作素材失败");
    } finally { setBusy(false); }
  }

  async function saveAndAttachToCurrentAvatar() {
    if (!finishedTaskId || !selectedAvatarId || busy) return;
    setBusy(true);
    try {
      const action = await saveGeneratedPersonalAction({ taskId: finishedTaskId, avatarId: selectedAvatarId });
      setPersonalAvatars(current => current.map(avatar => avatar.avatar_id === selectedAvatarId
        ? { ...avatar, actions: [...avatar.actions.filter(item => item.video_url !== action.video_url), action] }
        : avatar));
      localStorage.removeItem(taskStorageKey);
      setNotice("动作已保存并关联到当前数字人。");
      onActionSaved?.(action);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "动作保存失败");
    } finally { setBusy(false); }
  }

  async function createAvatar() {
    const source = avatarImage || image;
    if (!avatarName.trim() || !source || busy) return;
    setBusy(true);
    try {
      const form = new FormData();
      form.set("name", avatarName.trim());
      form.set("image", source);
      const response = await fetch("/api/user/avatars", { method: "POST", body: form });
      const payload = await response.json() as { avatar?: PersonalAvatar; error?: string };
      if (!response.ok || !payload.avatar) throw new Error(payload.error || "创建个人数字人失败");
      setPersonalAvatars(current => [...current, payload.avatar!]);
      setSelectedAvatarId(payload.avatar.avatar_id);
      setAvatarName("");
      setAvatarImage(null);
      setNotice("个人数字人已创建，可以关联动作素材。");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "创建个人数字人失败");
    } finally { setBusy(false); }
  }

  async function attachToAvatar(assetId: string) {
    if (!selectedAvatarId || busy) return;
    setBusy(true);
    try {
      const response = await fetch(`/api/user/avatars/${encodeURIComponent(selectedAvatarId)}/actions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ motionId: assetId }) });
      const payload = await response.json() as { action?: { video_url: string }; error?: string };
      if (!response.ok || !payload.action) throw new Error(payload.error || "关联动作素材失败");
      const action = payload.action;
      setPersonalAvatars(current => current.map(avatar => avatar.avatar_id === selectedAvatarId
        ? { ...avatar, actions: [...avatar.actions.filter(item => item.video_url !== action.video_url), action] }
        : avatar));
      setNotice("动作素材已关联到个人数字人。");
      if (returnToRoleId) router.push(`/roles/${encodeURIComponent(returnToRoleId)}`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "关联动作素材失败");
    } finally { setBusy(false); }
  }

  if (signedOut) return <section className={styles.work} data-embedded-action={embedded || undefined}><div className={styles.sectionHeading}><h2>登录后创建个人动作</h2></div><p className={styles.empty}>个人动作会保存到你的资源库并绑定当前形象。<Link href={`/api/user/login?next=${encodeURIComponent(`/roles/new/action?avatar_id=${initialAvatarId ?? ""}`)}`}>前往登录</Link></p></section>;
  if (!available) return embedded ? <section className={styles.work} data-embedded-action="true"><p className={styles.empty}>正在准备个人动作工作台…</p></section> : null;
  const selectedAvatar = personalAvatars.find((avatar) => avatar.avatar_id === selectedAvatarId);
  return <section className={styles.work} data-embedded-action={embedded || undefined} aria-label="个人 MiniMax 视频生成">
    <div className={styles.sectionHeading}><h2>{embedded ? `为 ${selectedAvatar?.display_name ?? "当前形象"} 创建动作` : "使用个人 Key 生成视频"}</h2><p>{embedded ? "当前形象已经锁定。生成并确认后，动作会自动回填到角色创建任务。" : "上传你有使用权的图片，生成 4–15 秒动作视频。生成会消耗你自己的 MiniMax API 额度；完成后可下载。"}</p></div>
    {!configured ? <p className={styles.empty}>尚未保存个人 MiniMax Key。<Link href="/settings/providers">前往供应商设置</Link></p>
      : !ready ? <p className={styles.empty}>付费视频生成尚未在当前环境启用。</p>
        : <div className={styles.personalForm}>
          {embedded ? <div className={styles.lockedResource}><span>当前形象</span><strong>{selectedAvatar?.display_name ?? "正在读取…"}</strong><small>使用该形象的源图生成动作，不会修改原图。</small></div>
            : <label>参考图片（JPG、PNG、WebP，≤ 4.5MB）<input type="file" accept="image/jpeg,image/png,image/webp" disabled={busy} onChange={event => setImage(event.target.files?.[0] || null)} /></label>}
          <label>动作提示词<textarea value={prompt} maxLength={2000} disabled={busy} onChange={event => setPrompt(event.target.value)} placeholder="描述人物要做的动作、镜头和情绪" /></label>
          <label>视频时长<SelectMenu fullWidth value={String(duration)} ariaLabel="视频时长" options={[...(Array.from({ length: 12 }, (_, index) => index + 4).map(seconds => ({ value: String(seconds), label: String(seconds + "秒") })))]} onChange={value => setDuration(Number(value))} disabled={busy} /></label>
          <label className={styles.confirm}><input type="checkbox" checked={confirmed} disabled={busy} onChange={event => setConfirmed(event.target.checked)} />我确认拥有图片使用权，并同意本次生成消耗个人 MiniMax API 额度</label>
          <button type="button" disabled={!image || !prompt.trim() || !confirmed || busy} onClick={() => void submit()}>{busy ? "生成中…" : `生成 ${duration} 秒视频`}</button>
        </div>}
    {notice ? <p className={styles.personalNotice} role="status">{notice}</p> : null}
    {resultUrl ? <div className={styles.personalResult}><video src={resultUrl} controls playsInline /><a className={styles.primary} href={resultUrl}>下载生成视频</a></div> : null}
    {embedded && finishedTaskId ? <button className={styles.primary} type="button" disabled={busy || !selectedAvatarId} onClick={() => void saveAndAttachToCurrentAvatar()}>{busy ? "正在保存…" : "保存动作并返回任务"}</button>
      : finishedTaskId && !assets.some(asset => asset.taskId === finishedTaskId) ? <button className={styles.primary} type="button" disabled={busy} onClick={() => void saveToLibrary()}>保存到个人动作素材库</button> : null}
    {!embedded && !returnToRoleId ? <div className={styles.personalForm}>
      <h3>我的数字人</h3>
      <label>名称<input type="text" value={avatarName} maxLength={50} disabled={busy} onChange={event => setAvatarName(event.target.value)} placeholder="给数字人起个名字" /></label>
      <label>形象图片（可使用上方已选图片）<input type="file" accept="image/jpeg,image/png,image/webp" disabled={busy} onChange={event => setAvatarImage(event.target.files?.[0] || null)} /></label>
      <button type="button" disabled={busy || !avatarName.trim() || !(avatarImage || image)} onClick={() => void createAvatar()}>创建个人数字人</button>
      {personalAvatars.length ? <label>关联动作的数字人<SelectMenu fullWidth value={String(selectedAvatarId)} ariaLabel="关联动作的数字人" options={[...(personalAvatars.map(avatar => ({ value: String(avatar.avatar_id), label: String(avatar.display_name) })))]} onChange={value => setSelectedAvatarId(value)} /></label> : null}
    </div> : null}
    {!embedded && assets.length ? <div className={styles.personalForm}><h3>我的动作素材</h3>{assets.map(asset => <div key={asset.id}><span>{asset.prompt.slice(0, 80)} · {asset.duration} 秒</span> <a href={`/api/user/motion-assets/${asset.id}`}>下载</a> {selectedAvatarId && !personalAvatars.find(avatar => avatar.avatar_id === selectedAvatarId)?.actions.some(action => action.video_url?.includes(asset.id)) ? <button type="button" disabled={busy} onClick={() => void attachToAvatar(asset.id)}>关联到数字人</button> : null}</div>)}</div> : null}
  </section>;
}

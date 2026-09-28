"use client";

import { BackLink } from "@/components/workspace/back-link";

import { useRouter } from "next/navigation";
import { Check, LoaderCircle, Upload } from "lucide-react";
import { useEffect, useState } from "react";
import styles from "./role-avatar-create-screen.module.css";

type Job = { id: string; state: "queued" | "processing" | "ready_for_review" | "success" | "failed"; error?: string; variant?: { video_url: string } };

export function RoleTalkingCreateScreen({ roleId, avatarId, actionId }: { roleId: string; avatarId: string; actionId: string }) {
  const router = useRouter();
  const [audio, setAudio] = useState<File | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const endpoint = `/api/user/avatars/${encodeURIComponent(avatarId)}/actions/${encodeURIComponent(actionId)}/talking-variants`;

  useEffect(() => {
    if (!avatarId || !actionId) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const response = await fetch(`${endpoint}/generate-lipforcing`, { cache: "no-store", signal: controller.signal });
        const payload = await response.json() as { job?: Job; error?: string };
        if (!response.ok) throw new Error(payload.error || "任务状态读取失败");
        if (!controller.signal.aborted) {
          setJob(payload.job ?? null);
          if (payload.job?.state === "queued" || payload.job?.state === "processing") timer = setTimeout(() => void poll(), 3000);
        }
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "任务状态读取失败");
      }
    };
    void poll();
    return () => { controller.abort(); if (timer) clearTimeout(timer); };
  }, [avatarId, actionId, endpoint, job?.state]);

  async function generate() {
    if (busy || !avatarId || !actionId) return;
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.set("roleId", roleId);
      if (audio) form.set("audio", audio);
      const response = await fetch(`${endpoint}/generate-lipforcing`, { method: "POST", body: form });
      const payload = await response.json() as { job?: Job; error?: string };
      if (!response.ok || !payload.job) throw new Error(payload.error || "口型对齐生成失败");
      setJob(payload.job);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "口型对齐生成失败"); }
    finally { setBusy(false); }
  }

  async function accept() {
    if (busy || !job || job.state !== "ready_for_review") return;
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`${endpoint}/accept`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ jobId: job.id }) });
      const payload = await response.json() as { error?: string };
      if (!response.ok) throw new Error(payload.error || "口型对齐保存失败");
      router.replace(`/roles/${encodeURIComponent(roleId)}`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "口型对齐保存失败"); setBusy(false); }
  }

  return <main className={styles.page}>
    <BackLink href={`/roles/${encodeURIComponent(roleId)}`} label="返回当前角色" />
    <section className={styles.card}>
      <span>离线数字人</span>
      <h1>创建口型对齐</h1>
      <p>Lip Forcing 会根据当前动作底片生成口型。默认使用角色声音作为参考，也可以上传自己的参考音频。</p>
      {!avatarId || !actionId ? <p className={styles.error} role="alert">缺少数字人或动作底片。</p> : <>
        <form onSubmit={(event) => { event.preventDefault(); void generate(); }}>
          <label htmlFor="reference-audio">参考音频（可选）</label>
          <input id="reference-audio" type="file" accept="audio/wav,audio/mpeg,audio/mp4,audio/x-m4a" onChange={(event) => setAudio(event.target.files?.[0] ?? null)} />
          {error || job?.error ? <p className={styles.error} role="alert">{error || job?.error}</p> : null}
          {job?.state === "queued" || job?.state === "processing" ? <p role="status">正在生成，完成后可预览。</p> : null}
          {job?.state !== "ready_for_review" && job?.state !== "success" ? <button type="submit" disabled={busy || job?.state === "queued" || job?.state === "processing" || Boolean(job?.error)}>{busy ? <LoaderCircle /> : <Upload />}{busy ? "正在提交…" : "生成口型对齐"}</button> : null}
        </form>
        {job?.variant?.video_url && (job.state === "ready_for_review" || job.state === "success") ? <div className={styles.review}><video src={job.variant.video_url} controls playsInline /><p>请先预览效果，再保存到当前形象。</p>{job.state === "ready_for_review" ? <button type="button" onClick={() => void accept()} disabled={busy}><Check />保存并返回角色</button> : <BackLink href={`/roles/${encodeURIComponent(roleId)}`} label="返回角色" />}</div> : null}
      </>}
    </section>
  </main>;
}

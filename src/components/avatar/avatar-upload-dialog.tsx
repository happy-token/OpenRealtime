"use client";

import Image from "next/image";
import { ImagePlus, LoaderCircle, Play, Upload, X } from "lucide-react";
import { useCallback, useEffect, useId, useState, type DragEvent } from "react";
import { createPortal } from "react-dom";
import type { AvatarDisplayConfig } from "@/components/digital-human/types";
import { createOwnedAvatar } from "@/lib/avatar-catalog-client";
import { acceptOwnedAvatarRealtimeBinding } from "@/lib/avatar-catalog-client";
import { useProviderKeyGate } from "@/components/provider-key/provider-key-gate";
import { isValidAnamAvatarName, suggestAnamAvatarName, ANAM_AVATAR_NAME_REQUIREMENT } from "@/lib/anam-avatar-name";
import type { AnamHostedAvatar } from "@/lib/anam-avatars";
import { readJsonResponse } from "@/lib/http-json-response";
import { normalizeAvatarSourceImage } from "@/lib/avatar-image-normalization";
import type { OwnedAvatarRecord } from "@/lib/avatar-records";
import styles from "./avatar-upload-dialog.module.css";

const MAX_UPLOAD_BYTES = 15 * 1024 * 1024;

export function displayNameFromImageFile(filename: string) {
  const name = filename.replace(/\.[^.]+$/, "").trim();
  return name && !name.startsWith(".") ? name.slice(0, 50) : "新形象";
}

export function createdAvatarDisplayConfig(
  current: AvatarDisplayConfig,
  avatar: OwnedAvatarRecord,
): AvatarDisplayConfig {
  return {
    ...current,
    renderPath: "segmented",
    segmentedAvatarId: avatar.avatar_id,
    segmentedDisplayName: avatar.display_name,
    segmentedAvatarActionId: "",
    motionTalkingVariantId: "",
  };
}

export function AvatarUploadDialog({
  onClose,
  onCreated,
  onRealtimeCreated,
  mode = "avatar",
  sourceAvatar,
  sourceName,
}: {
  onClose: () => void;
  onCreated?: (avatar: OwnedAvatarRecord) => void;
  onRealtimeCreated?: (avatar: OwnedAvatarRecord, hostedAvatar: AnamHostedAvatar) => void;
  mode?: "avatar" | "realtime";
  sourceAvatar?: OwnedAvatarRecord;
  sourceName?: string;
}) {
  const ensureProviderKey = useProviderKeyGate();
  const inputId = useId();
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState("");
  const [displayName, setDisplayName] = useState(sourceName ?? sourceAvatar?.display_name ?? "");
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [anamName, setAnamName] = useState(sourceAvatar ? suggestAnamAvatarName(sourceName ?? sourceAvatar.display_name) : "");
  const [ownedAvatar, setOwnedAvatar] = useState<OwnedAvatarRecord | null>(sourceAvatar ?? null);
  const [candidate, setCandidate] = useState<AnamHostedAvatar | null>(null);
  const previewImageUrl = sourceAvatar?.source_image_url ?? previewUrl;

  const requestClose = useCallback(() => {
    if (busy) return;
    if (mode === "realtime" && candidate && !window.confirm("实时形象尚未确认启用。现在离开可能占用 Anam 的创建额度，确定关闭吗？")) return;
    onClose();
  }, [busy, candidate, mode, onClose]);

  useEffect(() => {
    if (!file) {
      setPreviewUrl("");
      return;
    }
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) requestClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [busy, requestClose]);

  function chooseFile(next: File | undefined) {
    if (ownedAvatar) return;
    setDragging(false);
    setError("");
    if (!next) return;
    if (!next.type.startsWith("image/")) {
      setError("请选择 JPG、PNG、WEBP 等图片文件");
      return;
    }
    if (next.size > MAX_UPLOAD_BYTES) {
      setError("图片不能超过 15MB");
      return;
    }
    setFile(next);
    setDisplayName(displayNameFromImageFile(next.name));
    setAnamName(suggestAnamAvatarName(displayNameFromImageFile(next.name)));
  }

  async function createAvatar() {
    if (!file || busy) return;
    const name = displayName.trim();
    if (!name) {
      setError("请填写形象名称");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const sourceUrl = URL.createObjectURL(file);
      try {
        const sourceImageDataUrl = await normalizeAvatarSourceImage(sourceUrl);
        const avatar = await createOwnedAvatar({ displayName: name.slice(0, 50), sourceImageDataUrl });
        onCreated?.(avatar);
      } finally {
        URL.revokeObjectURL(sourceUrl);
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "形象创建失败，请重试");
    } finally {
      setBusy(false);
    }
  }

  async function createRealtime() {
    if ((!file && !sourceAvatar) || busy || candidate) return;
    if (!displayName.trim()) { setError("请填写形象名称"); return; }
    if (!isValidAnamAvatarName(anamName)) { setError(ANAM_AVATAR_NAME_REQUIREMENT); return; }
    try {
      if (!await ensureProviderKey("anam")) return;
      setBusy(true);
      setError("");
      let avatar = ownedAvatar;
      if (!avatar && file) {
        const sourceUrl = URL.createObjectURL(file);
        try {
          avatar = await createOwnedAvatar({ displayName: displayName.trim().slice(0, 50), sourceImageDataUrl: await normalizeAvatarSourceImage(sourceUrl) });
          setOwnedAvatar(avatar);
        } finally { URL.revokeObjectURL(sourceUrl); }
      }
      if (!avatar) throw new Error("请先选择形象图片");
      const response = await fetch(avatar.source_image_url);
      if (!response.ok) throw new Error("形象图片读取失败");
      const blob = await response.blob();
      const form = new FormData();
      form.set("displayName", anamName.trim());
      form.set("image", new File([blob], `${avatar.display_name}.jpg`, { type: blob.type || "image/jpeg" }));
      const result = await fetch("/api/anam/avatars", { method: "POST", body: form });
      const payload = await readJsonResponse<{ avatar?: AnamHostedAvatar; error?: string }>(result, "实时形象创建失败");
      if (!result.ok || !payload.avatar) throw new Error(payload.error || "实时形象创建失败");
      setCandidate(payload.avatar);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "实时形象创建失败"); }
    finally { setBusy(false); }
  }

  async function confirmRealtime() {
    if (!ownedAvatar || !candidate || busy) return;
    setBusy(true);
    setError("");
    try {
      if (sourceAvatar) {
        onRealtimeCreated?.(sourceAvatar, candidate);
        return;
      }
      const avatar = await acceptOwnedAvatarRealtimeBinding(ownedAvatar.avatar_id, {
        provider_avatar_id: candidate.id,
        avatar_model: candidate.activeVersion,
        preview_video_url: candidate.videoUrl,
      });
      onRealtimeCreated?.(avatar, candidate);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "实时形象绑定失败"); }
    finally { setBusy(false); }
  }

  if (typeof document === "undefined") return null;
  return createPortal(
    <div className={styles.backdrop} role="dialog" aria-modal="true" aria-labelledby={`${inputId}-title`} onMouseDown={(event) => {
      if (event.target === event.currentTarget && !busy) requestClose();
    }}>
      <section className={styles.panel}>
        <header>
          <div><small>DIGITAL HUMAN STUDIO</small><h2 id={`${inputId}-title`}>{mode === "realtime" ? "创建实时数字人" : "创建形象"}</h2></div>
          <button type="button" aria-label={mode === "realtime" ? "关闭创建实时数字人窗口" : "关闭创建形象窗口"} disabled={busy} onClick={requestClose}><X aria-hidden="true" /></button>
        </header>

        <div className={styles.body}>
          <div className={styles.intro}><ImagePlus aria-hidden="true" /><div><strong>{sourceAvatar ? "使用当前角色形象" : "上传一张清晰的人像图片"}</strong><span>{sourceAvatar ? "使用当前角色的形象图片生成实时数字人，确认效果后加入此角色。" : mode === "realtime" ? "上传后生成实时驱动效果，确认预览后才会启用。" : "建议正面、无遮挡、光线均匀；创建后会自动成为当前形象。"}</span></div></div>
          {candidate ? <div className={styles.candidatePreview}>
            {candidate.videoUrl ? <video src={candidate.videoUrl} controls autoPlay muted loop playsInline aria-label="实时数字人效果预览" /> : <p>实时效果正在处理。请确认后启用，稍后可在形象目录查看预览。</p>}
            <strong>{candidate.displayName}</strong>
          </div> : null}
          {!candidate ? <>
          <label
            className={styles.dropzone}
            data-dragging={dragging}
            data-filled={Boolean(previewImageUrl)}
            data-locked={Boolean(ownedAvatar)}
            htmlFor={inputId}
            onDragEnter={(event) => { event.preventDefault(); setDragging(true); }}
            onDragOver={(event) => event.preventDefault()}
            onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false); }}
            onDrop={(event: DragEvent<HTMLLabelElement>) => { event.preventDefault(); if (!sourceAvatar) chooseFile(event.dataTransfer.files[0]); }}
          >
            <input id={inputId} type="file" accept="image/*" disabled={busy || Boolean(ownedAvatar)} onChange={(event) => chooseFile(event.target.files?.[0])} />
            {previewImageUrl ? <Image src={previewImageUrl} alt="待创建形象预览" fill sizes="680px" unoptimized /> : null}
            <span className={styles.dropzoneWash} aria-hidden="true" />
            {!sourceAvatar ? <span className={styles.uploadPrompt}><Upload aria-hidden="true" /><strong>{file ? "更换图片" : "拖拽图片到这里"}</strong><small>{file ? file.name : "或点击整个区域选择图片"}</small><i>选择图片</i></span> : null}
          </label>

          <label className={styles.nameField}>
            <span>形象名称</span>
            <input value={displayName} maxLength={50} placeholder="例如：品牌主播" disabled={busy || Boolean(ownedAvatar)} onChange={(event) => { setDisplayName(event.target.value); if (mode === "realtime") setAnamName(suggestAnamAvatarName(event.target.value)); }} />
          </label>
          {mode === "realtime" ? <label className={styles.nameField}><span>实时形象名称</span><input value={anamName} maxLength={50} disabled={busy} onChange={(event) => setAnamName(event.target.value)} /><small>Anam 要求 3–50 个字符</small></label> : null}
          </> : null}
          {error ? <p className={styles.error} role="alert">{error}</p> : null}
        </div>

        <footer><button type="button" disabled={busy} onClick={requestClose}>取消</button><button type="button" disabled={busy || (mode === "realtime" ? !candidate && ((!file && !sourceAvatar) || !displayName.trim() || !isValidAnamAvatarName(anamName)) : !file || !displayName.trim())} onClick={() => void (mode === "realtime" ? candidate ? confirmRealtime() : createRealtime() : createAvatar())}>{busy ? <LoaderCircle aria-hidden="true" /> : mode === "realtime" ? <Play aria-hidden="true" /> : <ImagePlus aria-hidden="true" />}{busy ? "正在处理" : mode === "realtime" ? candidate ? "确认效果并启用" : "生成实时数字人" : "创建形象"}</button></footer>
      </section>
    </div>,
    document.body,
  );
}

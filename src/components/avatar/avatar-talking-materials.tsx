"use client";
import { useLanguage } from "@/components/language/language-provider";


import Link from "next/link";
import { Film, LoaderCircle, Play, RotateCcw, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { setOwnedAvatarTalkingVariantDeletion } from "@/lib/avatar-catalog-client";
import type { AvatarTalkingVariant, OwnedAvatarActionRecord } from "@/lib/avatar-records";
import styles from "./avatar-talking-materials.module.css";

const METHOD_NAMES: Record<AvatarTalkingVariant["method"], string> = {
  lipforcing: "Lip Forcing",
  musetalk: "MuseTalk 1.5",
  minimax: "MiniMax",
  wav2lip: "Wav2Lip",
};

export function AvatarTalkingMaterials({ avatarId, action, canManage, onActionUpdated, id = "talking-materials" }: {
  avatarId: string;
  action: OwnedAvatarActionRecord;
  canManage: boolean;
  onActionUpdated: (action: OwnedAvatarActionRecord) => void;
  id?: string;
}) {
  const { t } = useLanguage();
  const [preview, setPreview] = useState<AvatarTalkingVariant | null>(null);
  const [pendingDelete, setPendingDelete] = useState<AvatarTalkingVariant | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const variants = action.talking_variants ?? [];
  const active = variants.filter(item => !item.deleted_at);
  const deleted = variants.filter(item => item.deleted_at);

  useEffect(() => {
    if (!preview && !pendingDelete) return;
    const close = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || busyId) return;
      setPreview(null);
      setPendingDelete(null);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [busyId, pendingDelete, preview]);

  async function updateVariant(variant: AvatarTalkingVariant, shouldDelete: boolean) {
    if (busyId) return;
    setBusyId(variant.id);
    setError("");
    setNotice("");
    try {
      const updated = await setOwnedAvatarTalkingVariantDeletion(avatarId, action.avatar_action_id, variant.id, shouldDelete);
      onActionUpdated(updated);
      setPendingDelete(null);
      setNotice(shouldDelete ? `“${variant.display_name}”已移入已删除口型对齐` : `“${variant.display_name}”已恢复`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "口型对齐更新失败");
    } finally {
      setBusyId(null);
    }
  }

  function materialRow(variant: AvatarTalkingVariant, isDeleted: boolean) {
    const matchesSource = variant.source_video_url === action.video_url;
    return <article className={styles.row} key={variant.id} data-deleted={isDeleted}>
      <div className={styles.thumb}><Film aria-hidden="true" /></div>
      <div className={styles.copy}>
        <span>{METHOD_NAMES[variant.method]}<i aria-hidden="true" />{matchesSource ? t("已配对") : t("底片已变更")}</span>
        <strong>{variant.display_name}</strong>
      </div>
      <div className={styles.commands}>
        <button type="button" onClick={() => setPreview(variant)} aria-label={t("预览口型对齐：") + (variant.display_name) + ""}><Play aria-hidden="true" />{t("预览")}</button>
        {canManage ? isDeleted
          ? <button type="button" disabled={Boolean(busyId)} onClick={() => void updateVariant(variant, false)} aria-label={t("恢复口型对齐：") + (variant.display_name) + ""}><RotateCcw aria-hidden="true" />{t("恢复")}</button>
          : <button type="button" disabled={Boolean(busyId)} onClick={() => { setError(""); setPendingDelete(variant); }} aria-label={t("删除口型对齐：") + (variant.display_name) + ""} data-danger><Trash2 aria-hidden="true" />{t("删除")}</button>
          : null}
      </div>
    </article>;
  }

  return <section id={id} className={styles.section} aria-label={"" + (action.display_name) + t("的口型对齐")}>
    <header className={styles.header}>
      <div><span>{t("当前动作 · ")}{action.display_name}</span><h2>{t("口型对齐 ")}<em>{active.length}</em></h2></div>
      {canManage ? <Link href={`/avatars/create?task=lightweight&avatar_id=${encodeURIComponent(avatarId)}&avatar_action_id=${encodeURIComponent(action.avatar_action_id)}`}><Film aria-hidden="true" />{t("生成口型对齐")}</Link> : null}
    </header>
    {active.length ? <div className={styles.list}>{active.map(item => materialRow(item, false))}</div>
      : <div className={styles.empty}><Film aria-hidden="true" /><p>{t("此动作还没有可用的口型对齐。")}{canManage ? t("可以从当前底片生成配对版本。") : ""}</p></div>}
    {deleted.length ? <details className={styles.deleted}>
      <summary>{t("已删除口型对齐 ")}<span>{deleted.length}</span></summary>
      <div className={styles.list}>{deleted.map(item => materialRow(item, true))}</div>
    </details> : null}
    {notice ? <p className={styles.notice} role="status">{t(notice)}</p> : null}
    {error ? <p className={styles.error} role="alert">{t(error)}</p> : null}

    {preview ? createPortal(<div className={styles.backdrop} role="presentation" onMouseDown={event => event.target === event.currentTarget && setPreview(null)}>
      <section className={styles.previewDialog} role="dialog" aria-modal="true" aria-label={"" + (preview.display_name) + t(" 口型对齐预览")}>
        <header><div><span>{METHOD_NAMES[preview.method]}{t(" · 口型对齐")}</span><h3>{preview.display_name}</h3></div><button type="button" aria-label={t("关闭口型对齐预览")} onClick={() => setPreview(null)}><X /></button></header>
        <video key={preview.id} src={preview.video_url} controls autoPlay muted loop playsInline preload="auto" />
      </section>
    </div>, document.body) : null}

    {pendingDelete ? createPortal(<div className={styles.backdrop} role="presentation" onMouseDown={event => event.target === event.currentTarget && !busyId && setPendingDelete(null)}>
      <section className={styles.confirmDialog} role="dialog" aria-modal="true" aria-label={t("删除口型对齐")}>
        <span className={styles.confirmIcon}><Trash2 aria-hidden="true" /></span>
        <h3>{t("删除“")}{pendingDelete.display_name}”？</h3>
        <p>{t("它将从新会话的口型对齐选择中移除。“")}{action.display_name}{t("”底片和其他讲话版仍可使用。30 天内可在此恢复。")}</p>
        {error ? <p className={styles.error} role="alert">{t(error)}</p> : null}
        <footer><button type="button" disabled={Boolean(busyId)} onClick={() => setPendingDelete(null)}>{t("取消")}</button><button type="button" disabled={Boolean(busyId)} onClick={() => void updateVariant(pendingDelete, true)} data-danger>{busyId ? <LoaderCircle className={styles.spin} /> : <Trash2 />}{t("移入已删除口型对齐")}</button></footer>
      </section>
    </div>, document.body) : null}
  </section>;
}

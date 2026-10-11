"use client";
import { useLanguage, LocalizedText } from "@/components/language/language-provider";


import { Ellipsis, ImagePlus, Pencil, RotateCcw, Trash2 } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { renameOwnedAvatar, renameOwnedAvatarTalkingVariant, replaceOwnedAvatarSourceImage, setOwnedAvatarDeletion, setOwnedAvatarTalkingVariantDeletion, updateOwnedAvatarAction } from "@/lib/avatar-catalog-client";
import type { AvatarTalkingVariant, OwnedAvatarActionRecord, OwnedAvatarRecord } from "@/lib/avatar-records";
import styles from "./role-asset-management.module.css";

export type AssetTarget = { avatar: OwnedAvatarRecord; action?: OwnedAvatarActionRecord; variant?: AvatarTalkingVariant };
export type AssetChange = { avatarId: string; avatar?: OwnedAvatarRecord; action?: OwnedAvatarActionRecord };
type Operation = "rename" | "trash" | "restore" | "image";
type RequestOperation = (target: AssetTarget, operation: Operation) => void;

function targetName(target: AssetTarget) { return target.variant?.display_name ?? target.action?.display_name ?? target.avatar.display_name; }
function targetKind(target: AssetTarget) { return target.variant ? "口型对齐" : target.action ? "动作底片" : "形象"; }

export function AssetCard({ children, target, onManage, busy }: { children: ReactNode; target: AssetTarget; onManage: RequestOperation; busy: boolean }) {
  const { t } = useLanguage();
  const personal = target.avatar.avatar_id.startsWith("avatar-personal-");
  return <div className={styles.card}>
    {children}
    <details className={styles.menu}>
      <summary aria-label={t("管理") + (targetKind(target)) + "：" + (targetName(target)) + ""}><Ellipsis aria-hidden="true" /></summary>
      <div className={styles.menuItems}>
        <button type="button" disabled={busy} onClick={event => { event.currentTarget.closest("details")?.removeAttribute("open"); onManage(target, "rename"); }}><Pencil />{t("更名")}</button>
        {!personal && !target.action ? <button type="button" disabled={busy} onClick={event => { event.currentTarget.closest("details")?.removeAttribute("open"); onManage(target, "image"); }}><ImagePlus />{t("更换图片")}</button> : null}
        {!personal ? <button type="button" disabled={busy} data-danger onClick={event => { event.currentTarget.closest("details")?.removeAttribute("open"); onManage(target, "trash"); }}><Trash2 />{t("删除")}</button> : null}
      </div>
    </details>
  </div>;
}

export function DeletedAssets({ avatars, actionAvatar, talkingAction, onManage, busy }: {
  avatars?: OwnedAvatarRecord[]; actionAvatar?: OwnedAvatarRecord | null; talkingAction?: AssetTarget | null; onManage: RequestOperation; busy: boolean;
}) {
  const { t } = useLanguage();
  const targets: AssetTarget[] = avatars ? avatars.filter(avatar => avatar.deleted_at).map(avatar => ({ avatar }))
    : talkingAction?.action ? (talkingAction.action.talking_variants ?? []).filter(variant => variant.deleted_at).map(variant => ({ ...talkingAction, variant }))
    : actionAvatar ? actionAvatar.actions.filter(action => action.deleted_at).map(action => ({ avatar: actionAvatar, action })) : [];
  const supported = targets.filter(target => !target.avatar.avatar_id.startsWith("avatar-personal-"));
  if (!supported.length) return null;
  return <details className={styles.deleted}><summary>{t("已删除（")}{supported.length}）</summary>{supported.map(target => <div className={styles.deletedRow} key={target.variant?.id ?? target.action?.avatar_action_id ?? target.avatar.avatar_id}><span>{targetName(target)}</span><button type="button" disabled={busy} onClick={() => onManage(target, "restore")}><RotateCcw />{t("恢复")}</button></div>)}</details>;
}

export function applyAssetChange(records: OwnedAvatarRecord[], change: AssetChange) {
  return records.map(avatar => avatar.avatar_id !== change.avatarId ? avatar : change.avatar ?? {
    ...avatar, actions: avatar.actions.map(action => action.avatar_action_id === change.action?.avatar_action_id ? change.action : action),
  });
}

export function useRoleAssetManagement(onChanged: (change: AssetChange) => void) {
  const [request, setRequest] = useState<{ target: AssetTarget; operation: Operation } | null>(null);
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const dialogRef = useRef<HTMLDialogElement>(null);
  const triggerRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    if (!request) return;
    dialogRef.current?.showModal();
    return () => { triggerRef.current?.focus(); };
  }, [request]);

  function manage(target: AssetTarget, operation: Operation) {
    const active = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    triggerRef.current = active?.closest("details")?.querySelector("summary") ?? active;
    setName(targetName(target)); setFile(null); setError(""); setRequest({ target, operation });
  }
  async function submit() {
    if (!request || busy) return;
    const { target, operation } = request;
    const { avatar, action, variant } = target;
    setBusy(true); setError("");
    try {
      let change: AssetChange;
      if (operation === "image") {
        if (!file || !["image/jpeg", "image/png", "image/webp"].includes(file.type) || file.size > 4_500_000) throw new Error("请选择 4.5MB 以内的 JPG、PNG 或 WebP 图片");
        const sourceImageDataUrl = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result)); reader.onerror = () => reject(new Error("图片读取失败")); reader.readAsDataURL(file);
        });
        change = { avatarId: avatar.avatar_id, avatar: await replaceOwnedAvatarSourceImage(avatar.avatar_id, { sourceImageDataUrl, trashActions: true }) };
      } else if (variant && action) {
        change = { avatarId: avatar.avatar_id, action: operation === "rename"
          ? await renameOwnedAvatarTalkingVariant(avatar.avatar_id, action.avatar_action_id, variant.id, name.trim())
          : await setOwnedAvatarTalkingVariantDeletion(avatar.avatar_id, action.avatar_action_id, variant.id, operation === "trash") };
      } else if (action) {
        change = { avatarId: avatar.avatar_id, action: await updateOwnedAvatarAction(avatar.avatar_id, action.avatar_action_id, operation === "rename" ? { operation, displayName: name.trim() } : { operation }) };
      } else {
        change = { avatarId: avatar.avatar_id, avatar: operation === "rename" ? await renameOwnedAvatar(avatar.avatar_id, name.trim()) : await setOwnedAvatarDeletion(avatar.avatar_id, operation === "trash") };
      }
      onChanged(change); setRequest(null);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "素材更新失败"); }
    finally { setBusy(false); }
  }
  const dialog = request ? createPortal(<dialog ref={dialogRef} className={styles.dialog} aria-labelledby="role-asset-dialog-title" onKeyDown={event => { if (event.key === "Escape") event.stopPropagation(); }} onCancel={event => { event.preventDefault(); if (!busy) setRequest(null); }}>
    <form onSubmit={event => { event.preventDefault(); void submit(); }}>
      <h2 id="role-asset-dialog-title">{<LocalizedText text={request.operation === "rename" ? "更名" : request.operation === "trash" ? "删除" : request.operation === "image" ? "更换" : "恢复"} />}{targetKind(request.target)}</h2>
      <p>{targetName(request.target)}</p>
      {request.operation === "rename" ? <label>{<LocalizedText text={"新名称"} />}<input autoFocus value={name} maxLength={50} disabled={busy} onChange={event => setName(event.target.value)} required /></label> : request.operation === "image" ? <><label>{<LocalizedText text={"新图片"} />}<input autoFocus type="file" accept="image/jpeg,image/png,image/webp" disabled={busy} onChange={event => setFile(event.target.files?.[0] ?? null)} required /></label><p>{<LocalizedText text={"更换后会解除实时绑定，并将原动作移入回收站。使用此形象的其他角色也会受到影响；旧动作恢复后仍对应旧形象。"} />}</p></> : request.operation === "trash" ? <p>{<LocalizedText text={"素材将移入已删除列表，可恢复。使用该素材的其他角色也会受到影响。"} />}{<LocalizedText text={!request.target.action ? "形象下的动作和口型将暂时不可用。" : !request.target.variant ? "该底片的口型将暂时不可用。" : ""} />}</p> : <p>{<LocalizedText text={"恢复后可重新选择此素材。"} />}</p>}
      {error ? <p role="alert" className={styles.error}>{error}</p> : null}
      <footer><button type="button" disabled={busy} onClick={() => setRequest(null)}>{<LocalizedText text={"取消"} />}</button><button type="submit" disabled={busy || (request.operation === "rename" && (!name.trim() || name.trim() === targetName(request.target))) || (request.operation === "image" && !file)}>{<LocalizedText text={busy ? "正在保存…" : "确认"} />}</button></footer>
    </form>
  </dialog>, document.body) : null;
  return { manage, dialog, busy };
}

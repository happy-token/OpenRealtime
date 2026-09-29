"use client";
import { useLanguage } from "@/components/language/language-provider";


import Link from "next/link";
import { Film, LoaderCircle, Pencil, Plus, RotateCcw, Trash2, Video } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { renameOwnedAvatarTalkingVariant, setOwnedAvatarTalkingVariantDeletion } from "@/lib/avatar-catalog-client";
import type { AvatarTalkingVariant, OwnedAvatarActionRecord } from "@/lib/avatar-records";
import { WheelPicker, WheelPickerWrapper } from "@/components/ui/wheel-picker";
import styles from "./avatar-talking-material-rail.module.css";

const METHOD_NAMES: Record<AvatarTalkingVariant["method"], string> = {
  lipforcing: "Lip Forcing",
  musetalk: "MuseTalk 1.5",
  minimax: "MiniMax",
  wav2lip: "Wav2Lip",
};

function shortName(variant: AvatarTalkingVariant, actionName: string) {
  const prefix = `${actionName} · `;
  return variant.display_name.startsWith(prefix) && variant.display_name.length > prefix.length
    ? variant.display_name.slice(prefix.length)
    : variant.display_name;
}

export function AvatarTalkingMaterialRail({ avatarId, action, canManage, canDelete = canManage, canGenerate = canManage, selectedVariantId, onSelect, onActionUpdated, placement = "card", returnTo }: {
  avatarId: string;
  action: OwnedAvatarActionRecord;
  canManage: boolean;
  canDelete?: boolean;
  canGenerate?: boolean;
  selectedVariantId: string | null;
  onSelect: (variantId: string | null) => void;
  onActionUpdated: (action: OwnedAvatarActionRecord) => void;
  placement?: "card" | "detail";
  returnTo?: string;
}) {
  const { t } = useLanguage();
  const [pendingDelete, setPendingDelete] = useState<AvatarTalkingVariant | null>(null);
  const [renameTarget, setRenameTarget] = useState<AvatarTalkingVariant | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [renameError, setRenameError] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const renameTrigger = useRef<HTMLButtonElement>(null);
  const active = useMemo(() => (action.talking_variants ?? []).filter(variant => !variant.deleted_at), [action.talking_variants]);
  const deleted = (action.talking_variants ?? []).filter(variant => variant.deleted_at);
  const selectedVariant = active.find(variant => variant.id === selectedVariantId) ?? null;
  const detailWheel = placement === "detail";
  const baseValue = `base:${action.avatar_action_id}`;
  const generateHref = appendReturnTo(`/avatars/create?task=lightweight&avatar_id=${encodeURIComponent(avatarId)}&avatar_action_id=${encodeURIComponent(action.avatar_action_id)}`, returnTo);
  const wheelOptions = useMemo(() => [
    { value: baseValue, label: <span className={styles.optionLabel} title={t("动作底片：") + (action.display_name) + ""}>{t("底片")}</span>, textValue: action.display_name },
    ...active.map(variant => ({ value: `variant:${variant.id}`, label: <span className={styles.optionLabel} title={variant.display_name}>{shortName(variant, action.display_name)}</span>, textValue: variant.display_name })),
  ], [active, action.display_name, baseValue, t]);

  useEffect(() => {
    if ((!pendingDelete && !renameTarget) || busyId) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setPendingDelete(null);
        if (renameTarget) {
          setRenameTarget(null);
          setRenameError("");
          window.requestAnimationFrame(() => renameTrigger.current?.focus());
        }
      }
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [busyId, pendingDelete, renameTarget]);

  function beginRename(variant: AvatarTalkingVariant) {
    setRenameTarget(variant);
    setRenameValue(variant.display_name);
    setRenameError("");
    setError("");
    setNotice("");
  }

  function closeRename() {
    if (busyId) return;
    setRenameTarget(null);
    setRenameError("");
    window.requestAnimationFrame(() => renameTrigger.current?.focus());
  }

  async function submitRename() {
    if (!renameTarget || busyId) return;
    const name = renameValue.trim();
    if (!name || name.length > 50) {
      setRenameError("请输入 1–50 字的口型对齐名称");
      return;
    }
    if (name === renameTarget.display_name) { closeRename(); return; }
    setBusyId(renameTarget.id);
    setRenameError("");
    try {
      const updated = await renameOwnedAvatarTalkingVariant(avatarId, action.avatar_action_id, renameTarget.id, name);
      onActionUpdated(updated);
      setRenameTarget(null);
      setNotice(`已改名为“${name}”`);
      window.requestAnimationFrame(() => renameTrigger.current?.focus());
    } catch (cause) {
      setRenameError(cause instanceof Error ? cause.message : "口型对齐改名失败");
    } finally {
      setBusyId(null);
    }
  }

  async function updateVariant(variant: AvatarTalkingVariant, shouldDelete: boolean) {
    if (busyId) return;
    setBusyId(variant.id);
    setError("");
    setNotice("");
    try {
      const updated = await setOwnedAvatarTalkingVariantDeletion(avatarId, action.avatar_action_id, variant.id, shouldDelete);
      if (shouldDelete && selectedVariantId === variant.id) onSelect(null);
      onActionUpdated(updated);
      setPendingDelete(null);
      setNotice(shouldDelete ? "口型对齐已移入已删除列表" : "口型对齐已恢复");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "口型对齐更新失败");
    } finally {
      setBusyId(null);
    }
  }

  return <aside id={placement === "detail" ? "talking-materials" : undefined} className={styles.rail} data-placement={placement} aria-label={"" + (action.display_name) + t("素材切换")}>
    <div className={styles.heading}>
      <div><span>{t("当前动作")}</span><strong title={action.display_name}>{action.display_name}</strong></div>
    </div>
    {detailWheel ? <div className={styles.listRegion} role="region" aria-label={t("口型对齐列表")}>
      <div className={styles.wheelRegion} role="group" aria-label={"" + (action.display_name) + t("口型对齐选择")} onKeyDownCapture={event => {
        if (event.key === "Home") onSelect(null);
        if (event.key === "End") onSelect(active.at(-1)?.id ?? null);
      }}>
        <WheelPickerWrapper>
          <WheelPicker
            options={wheelOptions}
            value={selectedVariant ? `variant:${selectedVariant.id}` : baseValue}
            onValueChange={value => onSelect(value === baseValue ? null : value.slice("variant:".length))}
            optionItemHeight={33}
            visibleCount={20}
          />
        </WheelPickerWrapper>
      </div>
      <span className={styles.srOnly} role="status">{t("当前预览：")}{selectedVariant?.display_name ?? "" + (action.display_name) + t("动作底片")}</span>
    </div> : <div className={styles.scrollArea} role="region" aria-label={t("口型对齐列表")} tabIndex={0}>
      <button className={styles.base} type="button" aria-label={t("预览动作底片：") + (action.display_name) + ""} aria-pressed={selectedVariantId === null} onClick={() => onSelect(null)}>
        <Video aria-hidden="true" /><span><strong title={action.display_name}>{action.display_name}</strong><small>{t("动作底片")}</small></span>
      </button>
      <span className={styles.groupLabel}>{t("口型对齐 ")}<em>{active.length}</em></span>
      {active.length ? active.map(variant => <div className={styles.materialRow} key={variant.id} data-selected={selectedVariantId === variant.id}>
        <button type="button" aria-label={t("预览口型对齐：") + (variant.display_name) + ""} aria-pressed={selectedVariantId === variant.id} onClick={() => onSelect(variant.id)}>
          <Film aria-hidden="true" /><span><strong title={variant.display_name}>{shortName(variant, action.display_name)}</strong><small>{METHOD_NAMES[variant.method]}{variant.source_video_url !== action.video_url ? t(" · 底片已变更") : ""}</small></span>
        </button>
        {canDelete ? <button className={styles.deleteButton} type="button" aria-label={t("删除口型对齐：") + (variant.display_name) + ""} disabled={Boolean(busyId)} onClick={() => { setError(""); setPendingDelete(variant); }}><Trash2 aria-hidden="true" /></button> : null}
      </div>) : <p className={styles.empty}>{t("此动作还没有口型对齐")}</p>}
      {deleted.length ? <details className={styles.deleted}>
        <summary>{t("已删除素材 ")}<span>{deleted.length}</span></summary>
        {deleted.map(variant => <div className={styles.deletedRow} key={variant.id}>
          <span title={variant.display_name}>{shortName(variant, action.display_name)}</span>
          {canDelete ? <button type="button" aria-label={t("恢复口型对齐：") + (variant.display_name) + ""} disabled={Boolean(busyId)} onClick={() => void updateVariant(variant, false)}><RotateCcw aria-hidden="true" />{t("恢复")}</button> : null}
        </div>)}
      </details> : null}
    </div>}
    <div className={styles.footer}>
      {detailWheel && !active.length ? <p className={styles.empty}>{t("此动作还没有口型对齐")}</p> : null}
      {detailWheel && deleted.length ? <details className={styles.deleted}>
        <summary>{t("已删除素材 ")}<span>{deleted.length}</span></summary>
        <div className={styles.deletedList}>{deleted.map(variant => <div className={styles.deletedRow} key={variant.id}>
          <span title={variant.display_name}>{shortName(variant, action.display_name)}</span>
          {canDelete ? <button type="button" aria-label={t("恢复口型对齐：") + (variant.display_name) + ""} disabled={Boolean(busyId)} onClick={() => void updateVariant(variant, false)}><RotateCcw aria-hidden="true" />{t("恢复")}</button> : null}
        </div>)}</div>
      </details> : null}
      {detailWheel && (canManage || canDelete || canGenerate) ? <div className={styles.operations} role="group" aria-label={t("口型对齐操作")}>
        {canManage ? <button ref={renameTrigger} type="button" aria-label={selectedVariant ? t("修改口型对齐名称：") + (selectedVariant.display_name) + "" : t("请先选择口型对齐再改名")} title={selectedVariant ? t("修改口型对齐名称：") + (selectedVariant.display_name) + "" : t("请先选择口型对齐")} disabled={!selectedVariant || Boolean(busyId)} onClick={() => { if (selectedVariant) beginRename(selectedVariant); }}><Pencil aria-hidden="true" /><span>{t("改名")}</span></button> : null}
        {canDelete ? <button type="button" data-danger aria-label={selectedVariant ? t("删除口型对齐：") + (selectedVariant.display_name) + "" : t("请先选择口型对齐再删除")} title={selectedVariant ? t("删除口型对齐：") + (selectedVariant.display_name) + "" : t("请先选择口型对齐")} disabled={!selectedVariant || Boolean(busyId)} onClick={() => { if (selectedVariant) { setError(""); setPendingDelete(selectedVariant); } }}><Trash2 aria-hidden="true" /><span>{t("删除")}</span></button> : null}
        {canGenerate ? <Link aria-label={t("生成口型对齐")} title={t("生成口型对齐")} href={generateHref}><Plus aria-hidden="true" /><span>{t("生成")}</span></Link> : null}
      </div> : null}
      {!detailWheel && canGenerate ? <Link href={generateHref}><Plus aria-hidden="true" />{t("生成口型对齐")}</Link> : null}
      {notice ? <p role="status">{t(notice)}</p> : null}
      {error ? <p className={styles.error} role="alert">{t(error)}</p> : null}
    </div>

    {pendingDelete ? createPortal(<div className={styles.backdrop} role="presentation" onMouseDown={event => event.target === event.currentTarget && !busyId && setPendingDelete(null)}>
      <section className={styles.confirmDialog} role="dialog" aria-modal="true" aria-label={t("删除口型对齐")}>
        <span className={styles.confirmIcon}><Trash2 aria-hidden="true" /></span>
        <h3>{t("删除“")}{pendingDelete.display_name}”？</h3>
        <p>{t("它会从口型对齐选择中移除；动作底片和其他讲话版仍可使用。30 天内可在左侧列表恢复。")}</p>
        {error ? <p className={styles.error} role="alert">{t(error)}</p> : null}
        <footer><button type="button" disabled={Boolean(busyId)} onClick={() => setPendingDelete(null)}>{t("取消")}</button><button type="button" disabled={Boolean(busyId)} onClick={() => void updateVariant(pendingDelete, true)} data-danger>{busyId ? <LoaderCircle className={styles.spin} /> : <Trash2 />}{t("移入已删除口型对齐")}</button></footer>
      </section>
    </div>, document.body) : null}
    {renameTarget ? createPortal(<div className={styles.backdrop} role="presentation" onMouseDown={event => event.target === event.currentTarget && closeRename()}>
      <form className={`${styles.confirmDialog} ${styles.renameDialog}`} role="dialog" aria-modal="true" aria-label={t("修改口型对齐名称")} onSubmit={event => { event.preventDefault(); void submitRename(); }}>
        <span className={styles.confirmIcon}><Pencil aria-hidden="true" /></span>
        <h3>{t("修改口型对齐名称")}</h3>
        <label className={styles.renameField}><span>{t("名称")}</span><input autoFocus aria-label={t("新的口型对齐名称")} value={renameValue} maxLength={50} disabled={Boolean(busyId)} onChange={event => setRenameValue(event.target.value)} /></label>
        <p>{t("只修改显示名称，不影响预览视频或动作底片。")}</p>
        {renameError ? <p className={styles.error} role="alert">{t(renameError)}</p> : null}
        <footer><button type="button" disabled={Boolean(busyId)} onClick={closeRename}>{t("取消")}</button><button type="submit" disabled={Boolean(busyId) || !renameValue.trim() || renameValue.trim() === renameTarget.display_name}>{busyId ? <LoaderCircle className={styles.spin} /> : null}{t("保存名称")}</button></footer>
      </form>
    </div>, document.body) : null}
  </aside>;
}

function appendReturnTo(href: string, returnTo?: string) {
  if (!returnTo) return href;
  return `${href}&return_to=${encodeURIComponent(returnTo)}`;
}

"use client";
import { useLanguage } from "@/components/language/language-provider";


import { MoveDiagonal2, X } from "lucide-react";
import { createPortal } from "react-dom";
import { useEffect, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from "react";
import { AvatarActionStudio } from "@/components/avatar/avatar-action-studio";
import { AvatarLightweightConfig } from "@/components/avatar/avatar-lightweight-config";
import { AvatarStudio } from "@/components/avatar/avatar-studio";
import { fetchOwnedAvatar } from "@/lib/avatar-catalog-client";
import type { OwnedAvatarRecord } from "@/lib/avatar-records";
import type { AvatarWorkbenchTask } from "@/lib/avatar-workbench-navigation";
import styles from "./avatar-production-overlay.module.css";

export function AvatarProductionOverlay({
  task,
  avatarId,
  actionId,
  method,
  returnToRoleId,
  onClose,
  onComplete,
  onPreviewChange,
}: {
  task: AvatarWorkbenchTask;
  avatarId?: string;
  actionId?: string;
  method?: "lipforcing";
  returnToRoleId?: string;
  onClose: () => void;
  onComplete?: (result: { avatarId: string; actionId?: string; variantId?: string }) => void;
  onPreviewChange?: (preview: { url: string; name: string; kind?: "talking" } | null) => void;
}) {
  const { t } = useLanguage();
  const [mounted, setMounted] = useState(false);
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);
  const [size, setSize] = useState<{ width: number; height: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  const [resizing, setResizing] = useState(false);
  const panelRef = useRef<HTMLElement>(null);
  const dragRef = useRef<{ pointerId: number; startX: number; startY: number; left: number; top: number } | null>(null);
  const resizeRef = useRef<{ pointerId: number; startX: number; startY: number; width: number; height: number; left: number; top: number } | null>(null);
  useEffect(() => setMounted(true), []);
  const title = task === "avatar" ? "创建形象" : task === "motion" ? "生成动作" : task === "realtime" ? "创建数字人" : "生成口型动作";
  const movable = task === "motion" || task === "talking";

  function startDrag(event: ReactPointerEvent<HTMLElement>) {
    if (!movable || window.innerWidth <= 700 || !panelRef.current) return;
    if ((event.target as HTMLElement).closest("button, input, textarea, select, [role=combobox]")) return;
    const rect = panelRef.current.getBoundingClientRect();
    dragRef.current = { pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, left: rect.left, top: rect.top };
    setPosition({ left: rect.left, top: rect.top });
    setSize({ width: rect.width, height: rect.height });
    setDragging(true);
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function moveDialog(event: ReactPointerEvent<HTMLElement>) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId || !panelRef.current) return;
    const rect = panelRef.current.getBoundingClientRect();
    setPosition({
      left: Math.min(window.innerWidth - rect.width - 12, Math.max(12, drag.left + event.clientX - drag.startX)),
      top: Math.min(window.innerHeight - rect.height - 12, Math.max(12, drag.top + event.clientY - drag.startY)),
    });
  }

  function stopDrag(event: ReactPointerEvent<HTMLElement>) {
    if (dragRef.current?.pointerId !== event.pointerId) return;
    dragRef.current = null;
    setDragging(false);
    event.currentTarget.releasePointerCapture(event.pointerId);
  }

  function startResize(event: ReactPointerEvent<HTMLDivElement>) {
    if (!movable || window.innerWidth <= 700 || !panelRef.current) return;
    event.stopPropagation();
    const rect = panelRef.current.getBoundingClientRect();
    resizeRef.current = { pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, width: rect.width, height: rect.height, left: rect.left, top: rect.top };
    setPosition({ left: rect.left, top: rect.top });
    setSize({ width: rect.width, height: rect.height });
    setResizing(true);
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function resizeDialog(event: ReactPointerEvent<HTMLDivElement>) {
    const resize = resizeRef.current;
    if (!resize || resize.pointerId !== event.pointerId) return;
    setSize({
      width: Math.min(window.innerWidth - resize.left - 12, Math.max(task === "talking" ? 360 : 560, resize.width + event.clientX - resize.startX)),
      height: Math.min(window.innerHeight - resize.top - 12, Math.max(task === "talking" ? 280 : 152, resize.height + event.clientY - resize.startY)),
    });
  }

  function stopResize(event: ReactPointerEvent<HTMLDivElement>) {
    if (resizeRef.current?.pointerId !== event.pointerId) return;
    resizeRef.current = null;
    setResizing(false);
    event.currentTarget.releasePointerCapture(event.pointerId);
  }

  if (!mounted) return null;
  const panelStyle = movable && (position || size) ? {
    ...(position ? { left: `${position.left}px`, top: `${position.top}px`, right: "auto", bottom: "auto", transform: "none" } : {}),
    ...(size ? { width: `${size.width}px`, height: `${size.height}px` } : {}),
  } as CSSProperties : undefined;
  return createPortal(<div className={styles.backdrop} data-task={task} role="dialog" aria-modal={movable ? undefined : true} aria-label={title}>
    <section ref={panelRef} className={styles.panel} data-task={task} data-dragging={dragging || undefined} data-resizing={resizing || undefined} style={panelStyle}>
      <header title={movable ? t("拖动窗口") : undefined} onPointerDown={startDrag} onPointerMove={moveDialog} onPointerUp={stopDrag} onPointerCancel={stopDrag}><div><strong>{t(title)}</strong></div><button type="button" aria-label={t("关闭制作窗口")} onClick={onClose}><X aria-hidden="true" /></button></header>
      <div className={styles.content}>
        {task === "motion" ? avatarId ? <AvatarActionStudio
          avatarId={avatarId}
          embedded
          focusedCreation
          onPreviewChange={onPreviewChange}
          onSaved={(action) => onComplete?.({ avatarId, actionId: action.avatar_action_id })}
        /> : <p className={styles.missingAvatar}>{t("请先选择一个数字人形象。")}</p> : task === "talking" ? avatarId ? <TalkingProductionComposer
          avatarId={avatarId}
          actionId={actionId}
          method={method}
          onPreviewChange={onPreviewChange}
          onComplete={onComplete}
        /> : <p className={styles.missingAvatar}>{t("请先选择一个数字人形象。")}</p> : <AvatarStudio
          initialTask="realtime"
          initialAvatarId={avatarId}
          initialActionId={actionId}
          initialTalkingMethod={method}
          returnToRoleId={returnToRoleId}
          onComplete={onComplete}
          singleTask
        />}
      </div>
      {movable ? <div className={styles.resizeHandle} role="separator" aria-label={task === "talking" ? t("调整动作编排窗口大小") : t("调整生成动作窗口大小")} tabIndex={0} onPointerDown={startResize} onPointerMove={resizeDialog} onPointerUp={stopResize} onPointerCancel={stopResize}><MoveDiagonal2 aria-hidden="true" /></div> : null}
    </section>
  </div>, document.body);
}

function TalkingProductionComposer({ avatarId, actionId, method, onPreviewChange, onComplete }: {
  avatarId: string;
  actionId?: string;
  method?: "lipforcing";
  onPreviewChange?: (preview: { url: string; name: string; kind?: "talking" } | null) => void;
  onComplete?: (result: { avatarId: string; actionId?: string; variantId?: string }) => void;
}) {
  const { t } = useLanguage();
  const [avatar, setAvatar] = useState<OwnedAvatarRecord | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    void fetchOwnedAvatar(avatarId, controller.signal).then((record) => {
      if (!controller.signal.aborted) {
        setAvatar(record);
        setError(record ? "" : "未找到当前数字人形象");
      }
    }).catch((cause) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "数字人形象读取失败");
    });
    return () => controller.abort();
  }, [avatarId]);
  if (error) return <p className={styles.missingAvatar} role="alert">{t(error)}</p>;
  if (!avatar) return <p className={styles.missingAvatar}>{t("正在读取动作编排选项…")}</p>;
  return <AvatarLightweightConfig
    avatar={avatar}
    header={null}
    active
    open
    onOpenChange={() => undefined}
    initialActionId={actionId}
    initialMethod={method}
    previewBeforeSave
    floating
    onPreviewChange={onPreviewChange}
    onSaved={(variantId) => onComplete?.({ avatarId, actionId, variantId })}
  />;
}

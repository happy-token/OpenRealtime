"use client";
import { useLanguage } from "@/components/language/language-provider";


import Image from "next/image";
import { AudioLines, Check, Film, ImagePlus, MessageCircle, Plus, Sparkles, UserRound } from "lucide-react";
import { useEffect, useRef, type PointerEvent, type ReactNode } from "react";
import type { AvatarAction } from "@/lib/avatar-catalog";
import type { AvatarTalkingVariant } from "@/lib/avatar-records";
import Folder from "@/components/ui/folder";
import styles from "@/components/call/preview-workspace-lab.module.css";

export function shouldLoadAvatarPreviewDirectly(previewUrl: string) {
  return /^\/api\/avatars\/[^/]+\/image(?:\?|$)/.test(previewUrl);
}

export function PreviewVideo({ src, poster, label, active = true }: { src: string; poster?: string; label: string; active?: boolean }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    if (!active) { video.pause(); return; }
    void video.play().catch(() => undefined);
  }, [active, src]);
  return <video ref={videoRef} src={active ? src : undefined} poster={poster} aria-label={label} autoPlay={active} muted loop playsInline preload={active ? "auto" : "none"} onCanPlay={(event) => {
    if (active && event.currentTarget.paused) void event.currentTarget.play().catch(() => undefined);
  }} />;
}

export function WorkbenchMediaOption({
  name,
  eyebrow,
  image,
  video,
  selected,
  axis,
  icon,
  onSelect,
}: {
  name: string;
  eyebrow: string;
  image?: string | null;
  video?: string | null;
  selected: boolean;
  axis: "vertical" | "horizontal";
  icon?: ReactNode;
  onSelect: () => void;
}) {
  const { t } = useLanguage();
  return <button
    type="button"
    className={styles.edgeMediaOption}
    data-selected={selected}
    data-axis={axis}
    aria-label={t("选择") + (name) + ""}
    aria-pressed={selected}
    onClick={onSelect}
  >
    <span className={styles.edgeMediaVisual} data-placeholder={!video && !image}>
      {video ? <PreviewVideo src={video} poster={image ?? undefined} label={"" + (name) + t(" 动作预览")} /> : image ? (
        <Image src={image} alt="" fill sizes={axis === "vertical" ? "180px" : "150px"} unoptimized={shouldLoadAvatarPreviewDirectly(image)} />
      ) : icon ?? <UserRound aria-hidden="true" />}
    </span>
    <small>{eyebrow}</small>
    <strong>{name}</strong>
  </button>;
}

export function WorkbenchConversationOption({ selected, onSelect }: { selected: boolean; onSelect: () => void }) {
  return <WorkbenchMediaOption
    name="对话"
    eyebrow="语音模式"
    selected={selected}
    axis="horizontal"
    icon={<MessageCircle aria-hidden="true" />}
    onSelect={onSelect}
  />;
}

export function WorkbenchRealtimeOption({ selected, onSelect }: { selected: boolean; onSelect: () => void }) {
  return <WorkbenchMediaOption
    name="实时数字人"
    eyebrow="实时模式"
    selected={selected}
    axis="horizontal"
    icon={<Sparkles aria-hidden="true" />}
    onSelect={onSelect}
  />;
}

export function WorkbenchCreateCard({
  kind,
  title,
  note,
  axis,
  onCreate,
}: {
  kind: "avatar" | "motion" | "talking";
  title: string;
  note: string;
  axis: "vertical" | "horizontal";
  onCreate: () => void;
}) {
  const icon = kind === "avatar" ? <ImagePlus aria-hidden="true" /> : kind === "talking" ? <AudioLines aria-hidden="true" /> : <Sparkles aria-hidden="true" />;
  return <button type="button" className={styles.libraryCreateCard} data-axis={axis} aria-label={title} onClick={onCreate}>
    <span>{icon}</span><small>{note}</small><strong>{title}</strong>
  </button>;
}

function shortTalkingVariantName(actionName: string, variant: AvatarTalkingVariant) {
  const prefix = `${actionName} · `;
  return variant.display_name.startsWith(prefix) && variant.display_name.length > prefix.length
    ? variant.display_name.slice(prefix.length)
    : variant.display_name;
}

export function WorkbenchActionFolder({
  action,
  index,
  image,
  variants,
  selected,
  selectedVariantId,
  open,
  previewActive = true,
  onOpenChange,
  onSelectAction,
  onActionPointerDown,
  onActionPointerMove,
  onActionPointerUp,
  onActionPointerCancel,
  onSelectRuntime,
  runtimeSelected = false,
  onSelectVariant,
  onCreateTalking,
  talkingLabel = "口型动作",
  createLabel = "新建口型动作",
  createNote = "生成口型对齐",
  actionLabel = "底片",
}: {
  action: AvatarAction;
  index: number;
  image?: string;
  variants: AvatarTalkingVariant[];
  selected: boolean;
  selectedVariantId?: string;
  open: boolean;
  previewActive?: boolean;
  onOpenChange: (open: boolean) => void;
  onSelectAction?: () => boolean | void;
  onActionPointerDown?: (event: PointerEvent<HTMLButtonElement>) => void;
  onActionPointerMove?: (event: PointerEvent<HTMLButtonElement>) => void;
  onActionPointerUp?: (event: PointerEvent<HTMLButtonElement>) => void;
  onActionPointerCancel?: (event: PointerEvent<HTMLButtonElement>) => void;
  onSelectRuntime?: () => void;
  runtimeSelected?: boolean;
  onSelectVariant: (variantId: string) => void;
  onCreateTalking?: () => void;
  talkingLabel?: string;
  createLabel?: string;
  createNote?: string;
  actionLabel?: string;
}) {
  const { t } = useLanguage();
  return <Folder
    className={styles.actionMaterialFolder}
    frontClassName={styles.edgeMediaOption}
    ariaLabel={"" + (open ? "收起" : "展开") + "" + (action.displayName) + t("的") + (talkingLabel) + t("，共 ") + (variants.length) + t(" 个")}
    frontSelected={selected}
    open={open}
    onOpenChange={onOpenChange}
    onFrontClick={onSelectAction}
    onFrontPointerDown={onActionPointerDown}
    onFrontPointerMove={onActionPointerMove}
    onFrontPointerUp={onActionPointerUp}
    onFrontPointerCancel={onActionPointerCancel}
    selectedItemIndex={runtimeSelected && onSelectRuntime ? 0 : selectedVariantId && variants.some((variant) => variant.id === selectedVariantId) ? variants.findIndex((variant) => variant.id === selectedVariantId) + (onSelectRuntime ? 1 : 0) : -1}
    itemAriaLabels={[...(onSelectRuntime ? ["选择实时口型：使用此底片"] : []), ...variants.map((variant) => `选择${onSelectRuntime ? "预制口型" : talkingLabel}：${variant.display_name}`), ...(onCreateTalking ? [createLabel] : [])]}
    onItemSelect={(itemIndex) => {
      if (onSelectRuntime && itemIndex === 0) { onSelectRuntime(); return; }
      const variantIndex = itemIndex - (onSelectRuntime ? 1 : 0);
      const variant = variants[variantIndex];
      if (variant) onSelectVariant(variant.id);
      else if (variantIndex === variants.length) onCreateTalking?.();
    }}
    items={[...(onSelectRuntime ? [<span className={`${styles.actionFolderPaperContent} ${styles.actionFolderCreateContent}`} key="runtime"><AudioLines aria-hidden="true" /><strong>{t("实时口型")}</strong><small>{t("使用此底片")}</small></span>] : []), ...variants.map((variant) => <span className={styles.actionFolderPaperContent} key={variant.id}>
      {image ? <Image src={image} alt="" fill sizes="110px" unoptimized={shouldLoadAvatarPreviewDirectly(image)} /> : <Film aria-hidden="true" />}
      <i aria-hidden="true" /><strong>{shortTalkingVariantName(action.displayName, variant)}</strong>{selectedVariantId === variant.id ? <small className={styles.actionFolderSelected}><Check aria-hidden="true" />{t("已选中")}</small> : onSelectRuntime ? <small>{t("预制口型")}</small> : null}
    </span>), ...(onCreateTalking ? [<span className={`${styles.actionFolderPaperContent} ${styles.actionFolderCreateContent}`} key="create-talking">
      <Plus aria-hidden="true" /><strong>{createLabel}</strong><small>{createNote}</small>
    </span>] : [])]}
    front={<>
      <span className={styles.edgeMediaVisual}>
        {action.videoUrl ? <PreviewVideo src={action.videoUrl} poster={image} label={"" + (action.displayName) + t(" 动作预览")} active={previewActive} /> : image ? (
          <Image src={image} alt="" fill sizes="150px" unoptimized={shouldLoadAvatarPreviewDirectly(image)} />
        ) : <UserRound aria-hidden="true" />}
      </span>
      <small>{`${actionLabel} ${index + 1}`}</small><strong>{action.displayName}</strong>
      <span className={styles.actionFolderCount} aria-label={"" + (variants.length) + t(" 个") + (talkingLabel) + ""}>{variants.length}</span>
    </>}
  />;
}

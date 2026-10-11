"use client";

import { useLanguage } from "@/components/language/language-provider";


import Image from "next/image";
import { Check, ChevronLeft, ChevronRight, Film, ImageIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from "react";
import type { AvatarAction } from "@/lib/avatar-catalog";
import styles from "./avatar-media-coverflow.module.css";

export function avatarImageMediaId(avatarId: string) {
  return `image:${avatarId}`;
}

function CoverflowVideo({
  src,
  label,
  playing,
  preload,
  fit,
  onAspectRatio,
}: {
  src: string;
  label: string;
  playing: boolean;
  preload: "auto" | "metadata";
  fit: "landscape" | "square" | "portrait";
  onAspectRatio: (ratio: number) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    if (playing) {
      void video.play().catch(() => undefined);
      return;
    }
    video.pause();
  }, [playing, src]);

  return (
    <video
      ref={videoRef}
      src={src}
      aria-label={label}
      autoPlay={playing}
      data-playing={playing}
      muted
      loop
      playsInline
      preload={preload}
      data-fit={fit}
      onLoadedMetadata={(event) => {
        onAspectRatio(event.currentTarget.videoWidth / Math.max(1, event.currentTarget.videoHeight));
      }}
    />
  );
}

export function AvatarMediaCoverflow({
  avatarId,
  avatarName,
  imageUrl,
  actions,
  filterPlayableActions = true,
  activeIndex,
  active,
  selectedMediaId,
  size = "workbench",
  autoAdvanceActionsMs,
  onActiveIndexChange,
  onCurrentActionClick,
}: {
  avatarId: string;
  avatarName: string;
  imageUrl: string;
  actions: AvatarAction[];
  filterPlayableActions?: boolean;
  activeIndex: number;
  active: boolean;
  selectedMediaId?: string;
  size?: "compact" | "workbench" | "library";
  autoAdvanceActionsMs?: number;
  onActiveIndexChange: (index: number) => void;
  onCurrentActionClick?: (action: AvatarAction) => void;
}) {
  const { t } = useLanguage();
  const playableActions = useMemo(
    () => filterPlayableActions
      ? actions.filter((action) => action.state === "available" && action.pendingModelCount === 0 && Boolean(action.videoUrl))
      : actions,
    [actions, filterPlayableActions],
  );
  const mediaCount = playableActions.length + 1;
  const normalizedIndex = (activeIndex + mediaCount) % mediaCount;
  const currentAction = normalizedIndex > 0 ? playableActions[normalizedIndex - 1] ?? null : null;
  const pointerStartX = useRef<number | null>(null);
  const swipeConsumed = useRef(false);
  const [fitByActionId, setFitByActionId] = useState<Record<string, "landscape" | "square" | "portrait">>({});

  useEffect(() => {
    if (!active || !autoAdvanceActionsMs || playableActions.length === 0) return;
    const timer = window.setTimeout(() => {
      onActiveIndexChange((normalizedIndex + 1) % mediaCount);
    }, autoAdvanceActionsMs);
    return () => window.clearTimeout(timer);
  }, [active, autoAdvanceActionsMs, mediaCount, normalizedIndex, onActiveIndexChange, playableActions.length]);

  useEffect(() => {
    if (activeIndex < mediaCount) return;
    onActiveIndexChange(0);
  }, [activeIndex, mediaCount, onActiveIndexChange]);

  function showMedia(nextIndex: number) {
    onActiveIndexChange((nextIndex + mediaCount) % mediaCount);
  }

  function relativeOffset(index: number) {
    let offset = index - normalizedIndex;
    if (offset > mediaCount / 2) offset -= mediaCount;
    if (offset < -mediaCount / 2) offset += mediaCount;
    return offset;
  }

  function finishSwipe(event: ReactPointerEvent<HTMLDivElement>) {
    if (pointerStartX.current === null) return;
    const distance = event.clientX - pointerStartX.current;
    pointerStartX.current = null;
    if (Math.abs(distance) < 36) return;
    swipeConsumed.current = true;
    showMedia(normalizedIndex + (distance < 0 ? 1 : -1));
  }

  const mediaLabel = currentAction
    ? currentAction.state === "available" && currentAction.pendingModelCount === 0
      ? `当前预览：动作 · ${currentAction.displayName}`
      : `当前预览：待适配动作 · ${currentAction.displayName}`
    : `当前预览：形象 · ${avatarName}`;

  return (
    <div className={styles.root} data-size={size}>
      <div
        className={styles.viewport}
        role="group"
        aria-label={size === "workbench" ? "" + (avatarName) + t(" 形象与动作左右切换") : "" + (avatarName) + t(" 形象与动作层叠浏览")}
        onPointerDown={(event) => { pointerStartX.current = event.clientX; }}
        onPointerUp={finishSwipe}
        onPointerCancel={() => { pointerStartX.current = null; }}
      >
        {Array.from({ length: mediaCount }, (_, index) => {
          const action = index > 0 ? playableActions[index - 1] : null;
          const current = normalizedIndex === index;
          const offset = relativeOffset(index);
          const distance = Math.abs(offset);
          const mediaId = action?.avatarActionId ?? avatarImageMediaId(avatarId);
          return (
              <button
                key={mediaId}
              className={styles.card}
              type="button"
              aria-label={action ? t("预览动作：") + (action.displayName) + "" : t("预览 ") + (avatarName) + t(" 形象")}
              aria-current={current ? "true" : undefined}
              data-current={current}
              data-kind={action ? "action" : "image"}
              tabIndex={distance <= 2 ? 0 : -1}
              style={{
                "--coverflow-x": `${offset * (size === "library" ? 154 : size === "compact" ? 72 : 112)}px`,
                "--coverflow-scale": Math.max(.64, 1 - distance * .14),
                "--coverflow-turn": `${offset * -7}deg`,
                "--coverflow-opacity": Math.max(0, 1 - distance * .23),
                zIndex: 10 - distance,
              } as CSSProperties}
              onClick={() => {
                if (swipeConsumed.current) {
                  swipeConsumed.current = false;
                  return;
                }
                if (current && action && onCurrentActionClick) {
                  onCurrentActionClick(action);
                  return;
                }
                showMedia(index);
              }}
            >
              <span className={styles.media}>
                {action?.videoUrl ? (
                  <>
                    <Image className={styles.actionBackdrop} src={imageUrl} alt="" aria-hidden="true" fill sizes={size === "library" ? "310px" : size === "compact" ? "170px" : "230px"} unoptimized />
                    <CoverflowVideo
                      src={action.videoUrl}
                      label={`${avatarName} · ${action.displayName}`}
                      playing={active && current}
                      preload={current ? "auto" : "metadata"}
                      fit={fitByActionId[action.avatarActionId] ?? "square"}
                      onAspectRatio={(ratio) => {
                        setFitByActionId((currentFits) => ({
                          ...currentFits,
                          [action.avatarActionId]: ratio >= 1.2 ? "landscape" : ratio <= .82 ? "portrait" : "square",
                        }));
                      }}
                    />
                  </>
                ) : (
                  <>
                    <Image className={styles.mediaBackdrop} src={imageUrl} alt="" aria-hidden="true" fill sizes={size === "library" ? "310px" : size === "compact" ? "170px" : "100vw"} unoptimized />
                    <Image className={styles.mediaPortrait} src={imageUrl} alt={"" + (avatarName) + t(" 形象")} fill sizes={size === "library" ? "310px" : size === "compact" ? "170px" : "100vw"} unoptimized />
                  </>
                )}
              </span>
              <span className={styles.shade} />
              <span className={styles.copy}>
                {size === "compact" ? null : <small>{action
                  ? action.state === "available" && action.pendingModelCount === 0
                    ? t("Avatar 动作")
                    : t("待适配动作")
                  : t("Avatar 形象")}</small>}
                <strong>{action?.displayName ?? avatarName}</strong>
                <em>{current ? t("当前预览") : t("点击移至中央")}</em>
              </span>
              {size === "compact" ? null : (
                <span className={styles.kind}>
                  {action
                    ? action.state === "available" && action.pendingModelCount === 0
                      ? <><Film />{t("动作")}</>
                      : <><Film />{t("待适配动作")}</>
                    : <><ImageIcon />{t("形象")}</>
                  }
                </span>
              )}
              {selectedMediaId === mediaId ? <span className={styles.selected}><Check />{t("当前使用")}</span> : null}
            </button>
          );
        })}
      </div>
      <div className={styles.controls}>
        {mediaCount > 1 ? <button type="button" aria-label={t("浏览 ") + (avatarName) + t(" 的上一个媒体")} onClick={() => showMedia(normalizedIndex - 1)}><ChevronLeft /></button> : <span />}
        <strong>{t(mediaLabel)}</strong>
        {mediaCount > 1 ? <button type="button" aria-label={t("浏览 ") + (avatarName) + t(" 的下一个媒体")} onClick={() => showMedia(normalizedIndex + 1)}><ChevronRight /></button> : <span />}
      </div>
    </div>
  );
}

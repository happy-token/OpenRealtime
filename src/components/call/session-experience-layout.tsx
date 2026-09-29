"use client";
import { useLanguage } from "@/components/language/language-provider";


import { Columns2, Maximize2 } from "lucide-react";
import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import { fetchOwnedAvatar } from "@/lib/avatar-catalog-client";
import type { PageForm } from "./presentation-model";

interface SessionExperienceLayoutProps {
  pageForm: PageForm;
  surface: ReactNode;
  surfaceOverlay?: ReactNode;
  conversation: ReactNode;
  controls?: ReactNode;
  recovery?: ReactNode;
  ambientColor?: string | null;
  sourceAvatarId?: string;
  onEnterFullscreen: () => void;
  onEnterSidecar?: () => void;
}

type CompanionCorner = "top-left" | "top-right" | "bottom-left" | "bottom-right";

export function SessionExperienceLayout({
  pageForm,
  surface,
  surfaceOverlay,
  conversation,
  controls,
  recovery,
  ambientColor,
  sourceAvatarId,
  onEnterFullscreen,
  onEnterSidecar,
}: SessionExperienceLayoutProps) {
  const { t } = useLanguage();
  const [motionAspectRatio, setMotionAspectRatio] = useState(16 / 9);
  const [portraitAspectRatio, setPortraitAspectRatio] = useState<number | null>(null);
  useEffect(() => {
    setPortraitAspectRatio(null);
    if (!sourceAvatarId) return;
    const controller = new AbortController();
    let image: HTMLImageElement | undefined;
    void fetchOwnedAvatar(sourceAvatarId, controller.signal).then(avatar => {
      if (controller.signal.aborted || !avatar?.source_image_url) return;
      image = new Image();
      image.onload = () => {
        if (!controller.signal.aborted && image && image.naturalWidth && image.naturalHeight) {
          setPortraitAspectRatio(image.naturalWidth / image.naturalHeight);
        }
      };
      image.src = avatar.source_image_url;
    }).catch(() => { /* Keep the video ratio if the source image is unavailable. */ });
    return () => { controller.abort(); if (image) image.onload = null; };
  }, [sourceAvatarId]);
  const companionAspectRatio = portraitAspectRatio && portraitAspectRatio < 1 && motionAspectRatio > 1
    ? portraitAspectRatio : motionAspectRatio;
  const [companionCorner, setCompanionCorner] = useState<CompanionCorner>("bottom-right");
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });
  const [sidecarConversationWidth, setSidecarConversationWidth] = useState(58);
  const layoutRef = useRef<HTMLElement>(null);
  const dragStart = useRef<{ x: number; y: number } | null>(null);

  function beginDrag(event: PointerEvent<HTMLElement>) {
    if (pageForm !== "content" || event.button !== 0 || (event.target as HTMLElement).closest("button, input, textarea, a")) return;
    dragStart.current = { x: event.clientX, y: event.clientY };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function drag(event: PointerEvent<HTMLElement>) {
    if (!dragStart.current) return;
    setDragOffset({
      x: event.clientX - dragStart.current.x,
      y: event.clientY - dragStart.current.y,
    });
  }

  function finishDrag(event: PointerEvent<HTMLElement>) {
    if (!dragStart.current) return;
    if (event.type === "pointercancel" || Math.hypot(event.clientX - dragStart.current.x, event.clientY - dragStart.current.y) < 5) { dragStart.current = null; setDragOffset({ x: 0, y: 0 }); return; }
    const horizontal = event.clientX < window.innerWidth / 2 ? "left" : "right";
    const vertical = event.clientY < window.innerHeight / 2 ? "top" : "bottom";
    setCompanionCorner(`${vertical}-${horizontal}` as CompanionCorner);
    setDragOffset({ x: 0, y: 0 });
    dragStart.current = null;
  }

  function updateSidecarConversationWidth(clientX: number) {
    const bounds = layoutRef.current?.getBoundingClientRect();
    if (!bounds?.width) return;
    const next = Math.min(68, Math.max(38, ((clientX - bounds.left) / bounds.width) * 100));
    setSidecarConversationWidth(Math.round(next * 10) / 10);
  }

  function beginSidecarResize(event: PointerEvent<HTMLDivElement>) {
    if (pageForm !== "sidecar") return;
    event.currentTarget.setPointerCapture(event.pointerId);
    updateSidecarConversationWidth(event.clientX);
  }

  function resizeSidecar(event: PointerEvent<HTMLDivElement>) {
    if (!event.currentTarget.hasPointerCapture(event.pointerId)) return;
    updateSidecarConversationWidth(event.clientX);
  }

  function finishSidecarResize(event: PointerEvent<HTMLDivElement>) {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  }

  function adjustSidecarWidthByKeyboard(event: KeyboardEvent<HTMLDivElement>) {
    const delta = event.key === "ArrowLeft" ? -2 : event.key === "ArrowRight" ? 2 : 0;
    if (!delta) return;
    event.preventDefault();
    setSidecarConversationWidth(current => Math.min(68, Math.max(38, current + delta)));
  }

  const surfaceStyle = {
    "--companion-drag-x": `${dragOffset.x}px`,
    "--companion-drag-y": `${dragOffset.y}px`,
  } as CSSProperties;
  const layoutStyle = {
    "--sidecar-conversation-width": `${sidecarConversationWidth}%`,
    ...(ambientColor ? { "--session-avatar-ambient": ambientColor } : {}),
  } as CSSProperties;

  function enterFullscreenFromKeyboard(event: KeyboardEvent<HTMLElement>) {
    if ((event.target as HTMLElement).closest("button") || pageForm !== "content" || (event.key !== "Enter" && event.key !== " ")) return;
    event.preventDefault();
    onEnterFullscreen();
  }

  return (
    <section ref={layoutRef} className="session-experience-layout" data-page-form={pageForm} style={layoutStyle}>
      <section
        className="session-surface-region"
        data-corner={companionCorner}
        data-clickable={pageForm === "content"}
        aria-label={t("实时展示")}
        tabIndex={pageForm === "content" ? 0 : undefined}
        style={{ ...surfaceStyle, "--motion-aspect-ratio": companionAspectRatio } as CSSProperties}
        onLoadedMetadataCapture={(event) => { const video = event.target; if (video instanceof HTMLVideoElement && video.videoWidth && video.videoHeight && (!event.currentTarget.querySelector(".digital-human-motion-base-video") || video.classList.contains("digital-human-motion-base-video"))) setMotionAspectRatio(video.videoWidth / video.videoHeight); }}
        onPointerDown={beginDrag}
        onPointerMove={drag}
        onPointerUp={finishDrag}
        onPointerCancel={finishDrag}
        onKeyDown={enterFullscreenFromKeyboard}
      >
        <div className="session-surface-content">{surface}</div>
        {pageForm !== "content" ? surfaceOverlay : null}
        {pageForm === "content" && (
          <div className="session-surface-actions" role="toolbar" aria-label={t("小窗显示控制")}>
            <button type="button" className="session-surface-fullscreen" aria-label={t("全屏展示")} onClick={onEnterFullscreen}>
              <Maximize2 />
            </button>
            <button type="button" className="session-surface-sidecar" aria-label={t("并排展示")} onClick={onEnterSidecar}><Columns2 /></button>
          </div>
        )}
      </section>
      {pageForm === "content" && surfaceOverlay ? (
        <div className="session-content-stage-overlay">{surfaceOverlay}</div>
      ) : null}
      <section className="session-conversation-region" aria-label={t("对话内容")} aria-hidden={pageForm === "fullscreen"}>
        {conversation}
      </section>
      {pageForm === "sidecar" && <div
        className="session-sidecar-resizer"
        role="separator"
        aria-label={t("调整对话区宽度")}
        aria-orientation="vertical"
        aria-valuemin={38}
        aria-valuemax={68}
        aria-valuenow={sidecarConversationWidth}
        tabIndex={0}
        onPointerDown={beginSidecarResize}
        onPointerMove={resizeSidecar}
        onPointerUp={finishSidecarResize}
        onPointerCancel={finishSidecarResize}
        onKeyDown={adjustSidecarWidthByKeyboard}
      />}
      {recovery ? <div className="session-recovery-region">{recovery}</div> : null}
      {controls ? <div className="session-controls-region" aria-label={t("会话操作")}>
        {controls}
      </div> : null}
    </section>
  );
}

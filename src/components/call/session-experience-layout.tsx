"use client";

import { GripHorizontal, Maximize2, Minus, Plus } from "lucide-react";
import { useRef, useState, type CSSProperties, type KeyboardEvent, type MouseEvent, type PointerEvent, type ReactNode } from "react";
import type { PageForm } from "./presentation-model";

interface SessionExperienceLayoutProps {
  pageForm: PageForm;
  surface: ReactNode;
  surfaceOverlay?: ReactNode;
  conversation: ReactNode;
  controls?: ReactNode;
  recovery?: ReactNode;
  ambientColor?: string | null;
  onEnterFullscreen: () => void;
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
  onEnterFullscreen,
}: SessionExperienceLayoutProps) {
  const [companionMinimized, setCompanionMinimized] = useState(false);
  const [companionCorner, setCompanionCorner] = useState<CompanionCorner>("bottom-right");
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });
  const [sidecarConversationWidth, setSidecarConversationWidth] = useState(58);
  const layoutRef = useRef<HTMLElement>(null);
  const dragStart = useRef<{ x: number; y: number } | null>(null);

  function beginDrag(event: PointerEvent<HTMLButtonElement>) {
    if (pageForm !== "content") return;
    dragStart.current = { x: event.clientX, y: event.clientY };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function drag(event: PointerEvent<HTMLButtonElement>) {
    if (!dragStart.current) return;
    setDragOffset({
      x: event.clientX - dragStart.current.x,
      y: event.clientY - dragStart.current.y,
    });
  }

  function finishDrag(event: PointerEvent<HTMLButtonElement>) {
    if (!dragStart.current) return;
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

  function enterFullscreenFromCompanion(event: MouseEvent<HTMLElement>) {
    if (pageForm !== "content" || (event.target as HTMLElement).closest("button")) return;
    onEnterFullscreen();
  }

  function enterFullscreenFromKeyboard(event: KeyboardEvent<HTMLElement>) {
    if (pageForm !== "content" || (event.key !== "Enter" && event.key !== " ")) return;
    event.preventDefault();
    onEnterFullscreen();
  }

  return (
    <section ref={layoutRef} className="session-experience-layout" data-page-form={pageForm} style={layoutStyle}>
      <section
        className="session-surface-region"
        data-minimized={companionMinimized}
        data-corner={companionCorner}
        data-clickable={pageForm === "content"}
        aria-label="实时展示"
        tabIndex={pageForm === "content" ? 0 : undefined}
        style={surfaceStyle}
        onClick={enterFullscreenFromCompanion}
        onKeyDown={enterFullscreenFromKeyboard}
      >
        <div className="session-surface-content">{surface}</div>
        {pageForm !== "content" ? surfaceOverlay : null}
        {pageForm === "content" && (
          <div className="session-surface-actions" role="toolbar" aria-label="小窗显示控制">
            <button
              type="button"
              className="session-surface-drag"
              aria-label="移动小窗"
              onPointerDown={beginDrag}
              onPointerMove={drag}
              onPointerUp={finishDrag}
              onPointerCancel={finishDrag}
            >
              <GripHorizontal />
            </button>
            <button
              type="button"
              className="session-surface-minimize"
              aria-label={companionMinimized ? "展开小窗" : "最小化小窗"}
              onClick={() => setCompanionMinimized((minimized) => !minimized)}
            >
              {companionMinimized ? <Plus /> : <Minus />}
            </button>
            <button type="button" className="session-surface-fullscreen" aria-label="全屏展示" onClick={onEnterFullscreen}>
              <Maximize2 />
            </button>
          </div>
        )}
      </section>
      {pageForm === "content" && surfaceOverlay ? (
        <div className="session-content-stage-overlay">{surfaceOverlay}</div>
      ) : null}
      <section className="session-conversation-region" aria-label="对话内容" aria-hidden={pageForm === "fullscreen"}>
        {conversation}
      </section>
      {pageForm === "sidecar" && <div
        className="session-sidecar-resizer"
        role="separator"
        aria-label="调整对话区宽度"
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
      {controls ? <div className="session-controls-region" aria-label="会话操作">
        {controls}
      </div> : null}
    </section>
  );
}

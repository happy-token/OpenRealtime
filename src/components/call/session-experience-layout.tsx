"use client";

import { GripHorizontal, Maximize2, Minus, Plus } from "lucide-react";
import { useRef, useState, type CSSProperties, type KeyboardEvent, type MouseEvent, type PointerEvent, type ReactNode } from "react";
import type { PageForm } from "./presentation-model";

interface SessionExperienceLayoutProps {
  pageForm: PageForm;
  surface: ReactNode;
  conversation: ReactNode;
  onEnterFullscreen: () => void;
}

type CompanionCorner = "top-left" | "top-right" | "bottom-left" | "bottom-right";

export function SessionExperienceLayout({
  pageForm,
  surface,
  conversation,
  onEnterFullscreen,
}: SessionExperienceLayoutProps) {
  const [companionMinimized, setCompanionMinimized] = useState(false);
  const [companionCorner, setCompanionCorner] = useState<CompanionCorner>("bottom-right");
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });
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

  const surfaceStyle = {
    "--companion-drag-x": `${dragOffset.x}px`,
    "--companion-drag-y": `${dragOffset.y}px`,
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
    <section className="session-experience-layout" data-page-form={pageForm}>
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
      <section className="session-conversation-region" aria-label="对话内容" aria-hidden={pageForm === "fullscreen"}>
        {conversation}
      </section>
    </section>
  );
}

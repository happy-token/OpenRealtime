"use client";

import { useEffect, useState, type CSSProperties, type FocusEvent, type KeyboardEvent } from "react";
import {
  Captions,
  Keyboard,
  LayoutPanelTop,
  Mic,
  MicOff,
  Phone,
  Send,
  SlidersHorizontal,
} from "lucide-react";
import type { PageForm } from "./presentation-model";
import {
  DEFAULT_WORKBENCH_VISUAL_PREFERENCES,
  readWorkbenchVisualPreferences,
  WORKBENCH_VISUAL_PREFERENCES_EVENT,
  workbenchSurfaceTokens,
} from "@/lib/workbench-visual-preferences";

interface SessionControlBarProps {
  pageForm: PageForm;
  paused: boolean;
  captionsEnabled: boolean;
  onPageFormChange: (pageForm: PageForm) => void;
  onCaptionsChange: (enabled: boolean) => void;
  onPauseToggle: () => void;
  onOpenSettings: () => void;
  onTerminate: () => void;
  onSendText: (text: string) => boolean;
}

const PAGE_FORM_OPTIONS = [
  { id: "fullscreen", label: "全屏", description: "沉浸展示" },
  { id: "sidecar", label: "Sidecar", description: "对话与形象并排" },
  { id: "content", label: "内容", description: "内容优先、小窗陪伴" },
] as const satisfies ReadonlyArray<{ id: PageForm; label: string; description: string }>;

export function SessionControlBar({
  pageForm,
  paused,
  captionsEnabled,
  onPageFormChange,
  onCaptionsChange,
  onPauseToggle,
  onOpenSettings,
  onTerminate,
  onSendText,
}: SessionControlBarProps) {
  const [text, setText] = useState("");
  const [sendError, setSendError] = useState<string | null>(null);
  const [composerOpen, setComposerOpen] = useState(false);
  const [layoutMenuOpen, setLayoutMenuOpen] = useState(false);
  const [visualPreferences, setVisualPreferences] = useState(DEFAULT_WORKBENCH_VISUAL_PREFERENCES);
  const showComposer = pageForm !== "fullscreen" || composerOpen;
  const activePageForm = PAGE_FORM_OPTIONS.find((option) => option.id === pageForm) ?? PAGE_FORM_OPTIONS[0];

  useEffect(() => {
    const syncVisualPreferences = () => setVisualPreferences(readWorkbenchVisualPreferences());
    syncVisualPreferences();
    window.addEventListener("storage", syncVisualPreferences);
    window.addEventListener(WORKBENCH_VISUAL_PREFERENCES_EVENT, syncVisualPreferences);
    return () => {
      window.removeEventListener("storage", syncVisualPreferences);
      window.removeEventListener(WORKBENCH_VISUAL_PREFERENCES_EVENT, syncVisualPreferences);
    };
  }, []);

  const surfaceTokens = workbenchSurfaceTokens(visualPreferences);
  const surfaceStyle = {
    "--session-surface-alpha": surfaceTokens.surfaceAlpha,
    "--session-highlight-alpha": surfaceTokens.highlightAlpha,
    "--session-soft-alpha": surfaceTokens.softAlpha,
    "--session-blur": surfaceTokens.blur,
  } as CSSProperties;

  function submitText(event: React.FormEvent) {
    event.preventDefault();
    const value = text.trim();
    if (!value) return;
    if (!onSendText(value)) {
      setSendError("消息未发送，草稿已保留。请等待连接恢复后重试。");
      return;
    }
    setSendError(null);
    setText("");
    if (pageForm === "fullscreen") setComposerOpen(false);
  }

  function closeLayoutMenuAfterFocus(event: FocusEvent<HTMLDivElement>) {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
      setLayoutMenuOpen(false);
    }
  }

  function handleLayoutMenuKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "Escape") return;
    setLayoutMenuOpen(false);
    event.currentTarget.querySelector<HTMLButtonElement>(".session-action-btn")?.focus();
  }

  return (
    <div
      className="session-control-shell"
      data-view={pageForm}
      data-transparency={visualPreferences.transparency}
      data-glass-blur={visualPreferences.glassBlur}
      style={surfaceStyle}
    >
      {showComposer && (
        <form className="session-chat-input" onSubmit={submitText}>
          <div className="session-chat-field">
            <input
              autoFocus={pageForm === "fullscreen"}
              type="text"
              value={text}
              autoComplete="off"
              placeholder="输入文字…"
              aria-label="输入对话消息"
              onChange={(event) => setText(event.target.value)}
            />
            <button type="submit" className="session-send-btn" disabled={!text.trim()} aria-label="发送消息">
              <Send aria-hidden="true" />
              <span>发送</span>
            </button>
          </div>
          {sendError && <p role="alert">{sendError}</p>}
        </form>
      )}

      <div className="session-fixed-actions">
        <ControlButton
          label={paused ? "开启麦克风" : "关闭麦克风"}
          pressed={!paused}
          onClick={onPauseToggle}
        >
          {paused ? <MicOff /> : <Mic />}
        </ControlButton>
        <ControlButton
          label={composerOpen ? "收起文字输入" : "展开文字输入"}
          pressed={showComposer}
          onClick={() => setComposerOpen((open) => !open)}
        >
          <Keyboard />
        </ControlButton>
        <ControlButton
          label={captionsEnabled ? "隐藏临时字幕" : "显示临时字幕"}
          pressed={captionsEnabled}
          onClick={() => onCaptionsChange(!captionsEnabled)}
        >
          <Captions />
        </ControlButton>
        <div
          className="session-layout-menu-wrap"
          data-open={layoutMenuOpen}
          onPointerEnter={() => setLayoutMenuOpen(true)}
          onPointerLeave={() => setLayoutMenuOpen(false)}
          onFocus={() => setLayoutMenuOpen(true)}
          onBlur={closeLayoutMenuAfterFocus}
          onKeyDown={handleLayoutMenuKeyDown}
        >
          <ControlButton
            label={`页面形态：${activePageForm.label}`}
            expanded={layoutMenuOpen}
            onClick={() => setLayoutMenuOpen(true)}
          >
            <LayoutPanelTop />
          </ControlButton>
          <div
            className="session-layout-menu"
            data-open={layoutMenuOpen}
            role="menu"
            aria-label="页面形态"
            aria-hidden={!layoutMenuOpen}
          >
            {PAGE_FORM_OPTIONS.map((option) => (
              <button
                type="button"
                key={option.id}
                role="menuitemradio"
                aria-checked={pageForm === option.id}
                data-active={pageForm === option.id}
                onClick={(event) => {
                  onPageFormChange(option.id);
                  event.currentTarget
                    .closest(".session-layout-menu-wrap")
                    ?.querySelector<HTMLButtonElement>(".session-action-btn")
                    ?.focus();
                  setLayoutMenuOpen(false);
                }}
              >
                <span className="session-layout-diagram" data-form={option.id}><i /><i /></span>
                <span><strong>{option.label}</strong><small>{option.description}</small></span>
              </button>
            ))}
          </div>
        </div>
        <ControlButton label="会话设置" onClick={onOpenSettings}><SlidersHorizontal /></ControlButton>
        <ControlButton label="结束通话" danger onClick={onTerminate}><Phone className="session-hangup-icon" /></ControlButton>
      </div>
    </div>
  );
}

function ControlButton({
  label,
  children,
  danger = false,
  pressed,
  expanded,
  onClick,
}: {
  label: string;
  children: React.ReactNode;
  danger?: boolean;
  pressed?: boolean;
  expanded?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={`session-action-btn${danger ? " session-end-btn" : ""}`}
      aria-label={label}
      aria-pressed={pressed}
      aria-expanded={expanded}
      data-tooltip={label}
      onClick={onClick}
    >
      {children}
      <span className="sr-only">{label}</span>
    </button>
  );
}

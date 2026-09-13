"use client";

import { useEffect, useRef, useState, type CSSProperties, type FocusEvent, type KeyboardEvent } from "react";
import {
  Captions,
  Keyboard,
  LayoutPanelTop,
  Mic,
  MicOff,
  MoreHorizontal,
  Phone,
  Send,
  SlidersHorizontal,
  Square,
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
  assistantBusy: boolean;
  onStopReply: () => void;
  focusComposerRequest?: number;
  ended?: boolean;
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
  assistantBusy,
  onStopReply,
  focusComposerRequest = 0,
  ended = false,
}: SessionControlBarProps) {
  const [text, setText] = useState("");
  const [sendError, setSendError] = useState<string | null>(null);
  const [composerOpen, setComposerOpen] = useState(false);
  const [composerFocused, setComposerFocused] = useState(false);
  const [layoutMenuOpen, setLayoutMenuOpen] = useState(false);
  const [actionsMenuOpen, setActionsMenuOpen] = useState(false);
  const [visualPreferences, setVisualPreferences] = useState(DEFAULT_WORKBENCH_VISUAL_PREFERENCES);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const showComposer = !ended && (pageForm !== "fullscreen" || composerOpen);
  const compactActions = !ended && pageForm === "sidecar" && (composerFocused || Boolean(text.trim()) || actionsMenuOpen);
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

  useEffect(() => {
    if (!focusComposerRequest) return;
    setComposerOpen(true);
    requestAnimationFrame(() => composerRef.current?.focus());
  }, [focusComposerRequest]);

  useEffect(() => {
    if (!ended) return;
    setActionsMenuOpen(false);
    setComposerOpen(false);
  }, [ended]);

  const surfaceTokens = workbenchSurfaceTokens(visualPreferences);
  const surfaceStyle = {
    "--session-surface-alpha": surfaceTokens.surfaceAlpha,
    "--session-highlight-alpha": surfaceTokens.highlightAlpha,
    "--session-soft-alpha": surfaceTokens.softAlpha,
    "--session-blur": surfaceTokens.blur,
  } as CSSProperties;

  function resizeComposer() {
    const composer = composerRef.current;
    if (!composer) return;
    composer.style.height = "0px";
    composer.style.height = `${Math.min(composer.scrollHeight, 132)}px`;
  }

  function sendText() {
    const value = text.trim();
    if (!value) return;
    if (!onSendText(value)) {
      setSendError("消息未发送，草稿已保留。请等待连接恢复后重试。");
      return;
    }
    setSendError(null);
    setText("");
    requestAnimationFrame(resizeComposer);
    if (pageForm === "fullscreen") setComposerOpen(false);
  }

  function submitText(event: React.FormEvent) {
    event.preventDefault();
    sendText();
  }

  function handleTextInputAction() {
    if (pageForm !== "fullscreen") {
      composerRef.current?.focus();
      return;
    }
    if (composerOpen) {
      setComposerOpen(false);
      return;
    }
    setComposerOpen(true);
    requestAnimationFrame(() => composerRef.current?.focus());
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

  function closeOverflowMenu(event: FocusEvent<HTMLDivElement>) {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
      setActionsMenuOpen(false);
    }
  }

  return (
    <div
      className="session-control-shell"
      data-view={pageForm}
      data-transparency={visualPreferences.transparency}
      data-glass-blur={visualPreferences.glassBlur}
      data-ended={ended}
      style={surfaceStyle}
    >
      {showComposer && (
        <form className="session-chat-input" onSubmit={submitText}>
          <div className="session-chat-field">
            <textarea
              ref={composerRef}
              autoFocus={pageForm === "fullscreen"}
              rows={1}
              value={text}
              autoComplete="off"
              placeholder="输入文字…"
              aria-label="输入对话消息"
              onFocus={() => setComposerFocused(true)}
              onBlur={() => setComposerFocused(false)}
              onChange={(event) => {
                setText(event.target.value);
                requestAnimationFrame(resizeComposer);
              }}
              onKeyDown={(event) => {
                if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
                event.preventDefault();
                sendText();
              }}
            />
            <button type="submit" className="session-send-btn" disabled={!text.trim()} aria-label="发送消息">
              <Send aria-hidden="true" />
              <span>发送</span>
            </button>
          </div>
          {sendError && <p role="alert">{sendError}</p>}
        </form>
      )}

      <div className="session-fixed-actions" data-collapsed={compactActions}>
        {compactActions ? (
          <div className="session-actions-overflow-wrap" data-open={actionsMenuOpen} onBlur={closeOverflowMenu}>
            <ControlButton
              label="更多会话操作"
              expanded={actionsMenuOpen}
              onClick={() => setActionsMenuOpen((open) => !open)}
            >
              <MoreHorizontal />
            </ControlButton>
            <div className="session-actions-overflow" role="menu" aria-label="更多会话操作" aria-hidden={!actionsMenuOpen}>
              {assistantBusy ? <OverflowAction label="停止回复" onClick={() => { onStopReply(); setActionsMenuOpen(false); }}>
                <Square />
              </OverflowAction> : null}
              <OverflowAction label={paused ? "开启麦克风" : "关闭麦克风"} onClick={() => { onPauseToggle(); setActionsMenuOpen(false); }}>
                {paused ? <MicOff /> : <Mic />}
              </OverflowAction>
              <OverflowAction label={captionsEnabled ? "隐藏临时字幕" : "显示临时字幕"} onClick={() => { onCaptionsChange(!captionsEnabled); setActionsMenuOpen(false); }}>
                <Captions />
              </OverflowAction>
              <div className="session-overflow-layouts" aria-label="页面形态">
                <span>页面形态</span>
                <div>
                  {PAGE_FORM_OPTIONS.map((option) => (
                    <button
                      type="button"
                      key={option.id}
                      role="menuitemradio"
                      aria-checked={pageForm === option.id}
                      data-active={pageForm === option.id}
                      onClick={() => {
                        onPageFormChange(option.id);
                        setActionsMenuOpen(false);
                      }}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>
              <OverflowAction label="会话设置" onClick={() => { onOpenSettings(); setActionsMenuOpen(false); }}>
                <SlidersHorizontal />
              </OverflowAction>
              <OverflowAction label="结束通话" danger onClick={onTerminate}>
                <Phone className="session-hangup-icon" />
              </OverflowAction>
            </div>
          </div>
        ) : (
          <>
            <ControlButton
              label={paused ? "开启麦克风" : "关闭麦克风"}
              pressed={!paused}
              onClick={onPauseToggle}
              retireDirection="left"
              retireOrder={0}
              retired={ended}
            >
              {paused ? <MicOff /> : <Mic />}
            </ControlButton>
            <ControlButton
              label={pageForm === "fullscreen" ? (composerOpen ? "收起文字输入" : "展开文字输入") : "聚焦文字输入"}
              pressed={pageForm === "fullscreen" ? showComposer : composerFocused}
              onClick={handleTextInputAction}
              retireDirection="left"
              retireOrder={1}
              retired={ended}
            >
              <Keyboard />
            </ControlButton>
            {assistantBusy ? <ControlButton label="停止回复" onClick={onStopReply}>
              <Square />
            </ControlButton> : null}
            <ControlButton
              label={captionsEnabled ? "隐藏临时字幕" : "显示临时字幕"}
              pressed={captionsEnabled}
              onClick={() => onCaptionsChange(!captionsEnabled)}
              retireDirection="left"
              retireOrder={2}
              retired={ended}
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
            <ControlButton label="会话设置" retireDirection="right" retireOrder={1} retired={ended} onClick={onOpenSettings}><SlidersHorizontal /></ControlButton>
            <ControlButton label="结束通话" danger retireDirection="right" retireOrder={0} retired={ended} onClick={onTerminate}><Phone className="session-hangup-icon" /></ControlButton>
          </>
        )}
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
  retireDirection,
  retireOrder = 0,
  retired = false,
  onClick,
}: {
  label: string;
  children: React.ReactNode;
  danger?: boolean;
  pressed?: boolean;
  expanded?: boolean;
  retireDirection?: "left" | "right";
  retireOrder?: number;
  retired?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={`session-action-btn${danger ? " session-end-btn" : ""}`}
      aria-label={label}
      aria-pressed={pressed}
      aria-expanded={expanded}
      aria-hidden={retired || undefined}
      disabled={retired}
      tabIndex={retired ? -1 : undefined}
      data-tooltip={label}
      data-retire-on-end={retireDirection ? "true" : undefined}
      data-retire-direction={retireDirection}
      style={retireDirection ? { "--retire-delay": `${retireOrder * 45}ms` } as CSSProperties : undefined}
      onClick={onClick}
    >
      {children}
      <span className="sr-only">{label}</span>
    </button>
  );
}

function OverflowAction({
  label,
  children,
  danger = false,
  onClick,
}: {
  label: string;
  children: React.ReactNode;
  danger?: boolean;
  onClick: () => void;
}) {
  return (
    <button type="button" className={`session-overflow-action${danger ? " is-danger" : ""}`} role="menuitem" onClick={onClick}>
      {children}
      <span>{label}</span>
    </button>
  );
}

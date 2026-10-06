"use client";

import { useLanguage } from "@/components/language/language-provider";

import { useCallback, useEffect, useId, useRef, useState, type CSSProperties, type FocusEvent, type KeyboardEvent, type Ref } from "react";
import {
  Captions,
  ChevronDown,
  Keyboard,
  LayoutPanelTop,
  Mic,
  MicOff,
  MoreHorizontal,
  Phone,
  Send,
} from "lucide-react";
import type { PageForm } from "./presentation-model";
import {
  DEFAULT_WORKBENCH_VISUAL_PREFERENCES,
  readWorkbenchVisualPreferences,
  WORKBENCH_VISUAL_PREFERENCES_EVENT,
  workbenchSurfaceTokens,
} from "@/lib/workbench-visual-preferences";
import styles from "./session-control-bar.module.css";

interface SessionControlBarProps {
  pageForm: PageForm;
  paused: boolean;
  captionsEnabled: boolean;
  onPageFormChange: (pageForm: PageForm) => void;
  onCaptionsChange: (enabled: boolean) => void;
  onPauseToggle: () => void;
  onTerminate: () => void;
  onSendText: (text: string) => boolean;
  assistantBusy: boolean;
  onStopReply: () => void;
  focusComposerRequest?: number;
}

const PAGE_FORM_OPTIONS = [
  { id: "fullscreen", label: "全屏", description: "沉浸展示" },
  { id: "sidecar", label: "并排", description: "对话与形象并排" },
  { id: "content", label: "内容", description: "内容优先、小窗陪伴" },
] as const satisfies ReadonlyArray<{ id: PageForm; label: string; description: string }>;

export function SessionControlBar({
  pageForm,
  paused,
  captionsEnabled,
  onPageFormChange,
  onCaptionsChange,
  onPauseToggle,
  onTerminate,
  onSendText,
  focusComposerRequest = 0,
}: SessionControlBarProps) {
  const { t } = useLanguage();
  const [text, setText] = useState("");
  const [sendError, setSendError] = useState<string | null>(null);
  const [composerOpen, setComposerOpen] = useState(false);
  const [layoutMenuOpen, setLayoutMenuOpen] = useState(false);
  const [layoutMenuOffset, setLayoutMenuOffset] = useState(0);
  const [callActionsOpen, setCallActionsOpen] = useState(false);
  const [visualPreferences, setVisualPreferences] = useState(DEFAULT_WORKBENCH_VISUAL_PREFERENCES);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const inputToggleRef = useRef<HTMLButtonElement>(null);
  const layoutTriggerRef = useRef<HTMLButtonElement>(null);
  const layoutMenuRef = useRef<HTMLDivElement>(null);
  const moreRef = useRef<HTMLButtonElement>(null);
  const microphoneRef = useRef<HTMLButtonElement>(null);
  const callActionsRef = useRef<HTMLDivElement>(null);
  const lastFocusRequest = useRef(0);
  const composerId = useId();
  const layoutMenuId = useId();
  const callActionsId = useId();
  const showComposer = pageForm !== "fullscreen" || composerOpen;
  const condensed = pageForm === "fullscreen" && composerOpen;
  const callMenuVisible = condensed && callActionsOpen;
  const activePageForm = PAGE_FORM_OPTIONS.find((option) => option.id === pageForm) ?? PAGE_FORM_OPTIONS[0];

  const updateLayoutMenuPosition = useCallback(() => {
    const trigger = layoutTriggerRef.current;
    const menu = layoutMenuRef.current;
    if (!trigger || !menu || !trigger.offsetWidth) return;
    const rect = trigger.getBoundingClientRect();
    const scale = rect.width / trigger.offsetWidth;
    if (!scale) return;
    const center = rect.left + rect.width / 2;
    const halfMenu = menu.offsetWidth * scale / 2;
    const clamped = Math.max(10 + halfMenu, Math.min(window.innerWidth - 10 - halfMenu, center));
    setLayoutMenuOffset((clamped - center) / scale);
  }, []);

  useEffect(() => {
    if (!layoutMenuOpen) return;
    let frame = 0;
    let until = 0;
    const trackPosition = (now: number) => {
      updateLayoutMenuPosition();
      if (now < until) frame = requestAnimationFrame(trackPosition);
    };
    const trackTransition = () => {
      cancelAnimationFrame(frame);
      // Follow the 440ms toolbar and 260ms parent-panel transitions before settling.
      until = performance.now() + 500;
      frame = requestAnimationFrame(trackPosition);
    };
    trackTransition();
    window.addEventListener("resize", trackTransition);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", trackTransition);
    };
  }, [layoutMenuOpen, pageForm, condensed, updateLayoutMenuPosition]);

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
    setComposerOpen(false);
    setLayoutMenuOpen(false);
    setCallActionsOpen(false);
  }, [pageForm]);

  useEffect(() => {
    if (!composerOpen || pageForm !== "fullscreen") return;
    const frame = requestAnimationFrame(() => composerRef.current?.focus());
    return () => cancelAnimationFrame(frame);
  }, [composerOpen, pageForm]);

  useEffect(() => {
    if (!focusComposerRequest || lastFocusRequest.current === focusComposerRequest) return;
    lastFocusRequest.current = focusComposerRequest;
    setComposerOpen(true);
    const frame = requestAnimationFrame(() => composerRef.current?.focus());
    return () => cancelAnimationFrame(frame);
  }, [focusComposerRequest, pageForm]);

  useEffect(() => {
    if (!callMenuVisible) return;
    const frame = requestAnimationFrame(() => microphoneRef.current?.focus());
    const closeOutside = (event: PointerEvent) => {
      if (event.target instanceof Node && !callActionsRef.current?.contains(event.target)) {
        setCallActionsOpen(false);
        setLayoutMenuOpen(false);
      }
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("pointerdown", closeOutside);
    };
  }, [callMenuVisible]);

  const surfaceTokens = workbenchSurfaceTokens(visualPreferences);
  const surfaceStyle = {
    "--session-surface-alpha": surfaceTokens.surfaceAlpha,
    "--session-highlight-alpha": surfaceTokens.highlightAlpha,
    "--session-soft-alpha": surfaceTokens.softAlpha,
    "--session-blur": surfaceTokens.blur,
    width: "var(--call-toolbar-width)",
    minHeight: "var(--call-toolbar-height)",
    padding: "var(--call-toolbar-padding)",
    borderRadius: "var(--call-toolbar-radius)",
    gap: "var(--call-toolbar-gap)",
    flexWrap: "nowrap",
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
    if (pageForm === "fullscreen") closeComposer();
  }

  function submitText(event: React.FormEvent) {
    event.preventDefault();
    sendText();
  }

  function handleTextInputAction() {
    if (composerOpen) {
      closeComposer();
      return;
    }
    setComposerOpen(true);
    setLayoutMenuOpen(false);
  }

  function closeComposer() {
    setComposerOpen(false);
    setCallActionsOpen(false);
    setLayoutMenuOpen(false);
    inputToggleRef.current?.focus();
  }

  function handleToolbarKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "Escape") return;
    if (callMenuVisible) {
      event.preventDefault();
      event.stopPropagation();
      setCallActionsOpen(false);
      setLayoutMenuOpen(false);
      moreRef.current?.focus();
    } else if (condensed) {
      event.preventDefault();
      event.stopPropagation();
      closeComposer();
    }
  }

  function closeLayoutMenuAfterFocus(event: FocusEvent<HTMLDivElement>) {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
      setLayoutMenuOpen(false);
    }
  }

  function openLayoutMenu() {
    updateLayoutMenuPosition();
    setLayoutMenuOpen(true);
  }

  function handleLayoutMenuKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "Escape" || !layoutMenuOpen) return;
    event.preventDefault();
    event.stopPropagation();
    setLayoutMenuOpen(false);
    layoutTriggerRef.current?.focus();
  }

  return (
    <div
      className={`session-control-shell ${styles.shell}`}
      data-view={pageForm}
      data-composer-open={showComposer}
      data-transparency={visualPreferences.transparency}
      data-glass-blur={visualPreferences.glassBlur}
      style={surfaceStyle}
      onKeyDown={handleToolbarKeyDown}
    >
      <form id={composerId} className={styles.composer} onSubmit={submitText} inert={!showComposer} aria-hidden={!showComposer}>
        <div className={styles.field}>
          <textarea
            ref={composerRef}
            rows={1}
            value={text}
            autoComplete="off"
            placeholder={t("输入文字…")}
            aria-label={t("输入对话消息")}
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
          <button type="submit" className="session-send-btn" disabled={!text.trim()} aria-label={t("发送消息")}>
            <Send aria-hidden="true" />
            <span>{t("发送")}</span>
          </button>
        </div>
        {sendError && <p role="alert" className={styles.error}>{sendError}</p>}
      </form>

      <div className={styles.actions}>
        {pageForm === "fullscreen" && <ControlButton
          buttonRef={inputToggleRef}
          label={composerOpen ? t("收起文字输入") : t("展开文字输入")}
          pressed={showComposer}
          expanded={composerOpen}
          controls={composerId}
          onClick={handleTextInputAction}
        >
          {composerOpen ? <ChevronDown /> : <Keyboard />}
        </ControlButton>}
        {pageForm === "fullscreen" && !condensed && <ControlButton label={captionsEnabled ? t("隐藏临时字幕") : t("显示临时字幕")} pressed={captionsEnabled} onClick={() => onCaptionsChange(!captionsEnabled)}><Captions /></ControlButton>}
        <div className={styles.callActions} data-condensed={condensed} data-open={callMenuVisible} ref={callActionsRef}
          onBlur={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
              setCallActionsOpen(false);
              setLayoutMenuOpen(false);
            }
          }}>
          {condensed && <ControlButton buttonRef={moreRef} label={t("展开通话操作")} expanded={callMenuVisible} controls={callActionsId} onClick={() => setCallActionsOpen(!callActionsOpen)}><MoreHorizontal /></ControlButton>}
          <div id={callActionsId} className={styles.primaryActions} role="group" aria-label={t("通话操作")} aria-hidden={condensed && !callMenuVisible} inert={condensed && !callMenuVisible}>
            <ControlButton buttonRef={microphoneRef}
              label={paused ? t("开启麦克风") : t("关闭麦克风")}
              pressed={!paused}
              onClick={onPauseToggle}
            >
              {paused ? <MicOff /> : <Mic />}
            </ControlButton>
            <div
              className="session-layout-menu-wrap"
              data-open={layoutMenuOpen}
              onPointerEnter={openLayoutMenu}
              onPointerLeave={() => setLayoutMenuOpen(false)}
              onFocus={(event) => {
                if (!event.currentTarget.contains(event.relatedTarget as Node | null)) openLayoutMenu();
              }}
              onBlur={closeLayoutMenuAfterFocus}
              onKeyDown={handleLayoutMenuKeyDown}
            >
              <ControlButton
                buttonRef={layoutTriggerRef}
                label={t("页面形态：") + (activePageForm.label) + ""}
                expanded={layoutMenuOpen}
                controls={layoutMenuId}
                popup="menu"
                onClick={openLayoutMenu}
              >
                <LayoutPanelTop />
              </ControlButton>
              <div
                id={layoutMenuId}
                ref={layoutMenuRef}
                className="session-layout-menu"
                style={{ left: `calc(50% + ${layoutMenuOffset}px)`, right: "auto" }}
                data-open={layoutMenuOpen}
                role="menu"
                aria-label={t("页面形态")}
                aria-hidden={!layoutMenuOpen}
                inert={!layoutMenuOpen}
              >
                {PAGE_FORM_OPTIONS.map((option) => (
                  <button
                    type="button"
                    key={option.id}
                    role="menuitemradio"
                    aria-checked={pageForm === option.id}
                    data-active={pageForm === option.id}
                    onClick={(event) => {
                      setComposerOpen(false);
                      setCallActionsOpen(false);
                      onPageFormChange(option.id);
                      event.currentTarget
                        .closest(".session-layout-menu-wrap")
                        ?.querySelector<HTMLButtonElement>(".session-action-btn")
                        ?.focus();
                      setLayoutMenuOpen(false);
                    }}
                  >
                    <span className="session-layout-diagram" data-form={option.id}><i /><i /></span>
                    <span><strong>{t(option.label)}</strong><small>{t(option.description)}</small></span>
                  </button>
                ))}
              </div>
            </div>
            {condensed &&
              <ControlButton label={captionsEnabled ? t("隐藏临时字幕") : t("显示临时字幕")} pressed={captionsEnabled} onClick={() => onCaptionsChange(!captionsEnabled)}><Captions /></ControlButton>
            }
            <ControlButton label={t("结束通话")} danger onClick={onTerminate}><Phone className="session-hangup-icon" /></ControlButton>
          </div>
        </div>
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
  controls,
  popup,
  buttonRef,
  onClick,
}: {
  label: string;
  children: React.ReactNode;
  danger?: boolean;
  pressed?: boolean;
  expanded?: boolean;
  controls?: string;
  popup?: "menu";
  buttonRef?: Ref<HTMLButtonElement>;
  onClick: () => void;
}) {
  const { t } = useLanguage();
  return (
    <button
      type="button"
      ref={buttonRef}
      className={`session-action-btn${danger ? " session-end-btn" : ""}`}
      aria-label={label}
      aria-pressed={pressed}
      aria-expanded={expanded}
      aria-controls={controls}
      aria-haspopup={popup}
      data-tooltip={label}
      onClick={onClick}
    >
      {children}
      <span className="sr-only">{t(label)}</span>
    </button>
  );
}

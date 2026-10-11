"use client";

import { useLanguage } from "@/components/language/language-provider";


import { ArrowRight, Check, ChevronLeft, ChevronRight, Pause, Play } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type WheelEvent } from "react";
import type { AvatarDisplayConfig, ExperienceMode } from "@/components/digital-human/types";
import { EXPERIENCE_MODE_OPTIONS } from "@/components/digital-human/types";
import { VoiceStartButton } from "@/components/ui/voice-start-button";
import { ExperienceModeDemo } from "./experience-mode-demo";
import type { VoiceVisualTheme } from "./voice-theme";
import styles from "./experience-mode-carousel.module.css";

export const DEFAULT_MODE_CAROUSEL_INTERVAL_MS = 4200;

const MODE_META: Record<ExperienceMode, { number: string; action: string }> = {
  voice: { number: "01", action: "进入对话" },
  avatar: { number: "02", action: "选择数字人" },
};

interface ExperienceModeCarouselProps {
  value: ExperienceMode;
  onChange: (mode: ExperienceMode) => void;
  avatarDisplayConfig: AvatarDisplayConfig;
  avatarArtifactPreviewEnabled: boolean;
  connected: boolean;
  onStartSession: (mode?: ExperienceMode) => void;
  error: string | null;
  active?: boolean;
  reduceMotion?: boolean;
  autoPlayIntervalMs?: number;
  voiceVisualTheme?: VoiceVisualTheme;
}

export function ExperienceModeCarousel({
  value,
  onChange,
  avatarDisplayConfig,
  avatarArtifactPreviewEnabled,
  connected,
  onStartSession,
  error,
  active = true,
  reduceMotion = false,
  autoPlayIntervalMs = DEFAULT_MODE_CAROUSEL_INTERVAL_MS,
  voiceVisualTheme = "cloud",
}: ExperienceModeCarouselProps) {
  const { t } = useLanguage();
  const [hoverPaused, setHoverPaused] = useState(false);
  const [manualPause, setManualPause] = useState(false);
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(true);
  const wheelLock = useRef(false);
  const motionPaused = hoverPaused || manualPause || reduceMotion || prefersReducedMotion || !active;

  const move = useCallback((delta: 1 | -1) => {
    const current = EXPERIENCE_MODE_OPTIONS.findIndex((option) => option.id === value);
    onChange(EXPERIENCE_MODE_OPTIONS[(current + delta + EXPERIENCE_MODE_OPTIONS.length) % EXPERIENCE_MODE_OPTIONS.length].id);
  }, [onChange, value]);

  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setPrefersReducedMotion(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    if (motionPaused || autoPlayIntervalMs <= 0) return;
    const timer = window.setTimeout(() => move(1), autoPlayIntervalMs);
    return () => window.clearTimeout(timer);
  }, [autoPlayIntervalMs, motionPaused, move]);

  function positionFor(mode: ExperienceMode) {
    const selectedIndex = EXPERIENCE_MODE_OPTIONS.findIndex((option) => option.id === value);
    const index = EXPERIENCE_MODE_OPTIONS.findIndex((option) => option.id === mode);
    if (EXPERIENCE_MODE_OPTIONS.length === 2 && index !== selectedIndex) {
      return selectedIndex === 0 ? "next" : "previous";
    }
    const offset = (index - selectedIndex + EXPERIENCE_MODE_OPTIONS.length) % EXPERIENCE_MODE_OPTIONS.length;
    return offset === 0 ? "active" : offset === 1 ? "next" : "previous";
  }

  function handleCardKeyDown(event: KeyboardEvent<HTMLElement>, mode: ExperienceMode) {
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      move(event.key === "ArrowRight" ? 1 : -1);
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      activateMode(mode);
    }
  }

  function activateMode(mode: ExperienceMode) {
    onChange(mode);
    if (mode === "avatar") onStartSession(mode);
  }

  function handleWheel(event: WheelEvent<HTMLElement>) {
    const distance = event.deltaX + event.deltaY;
    if (wheelLock.current || Math.abs(distance) < 16) return;
    wheelLock.current = true;
    move(distance > 0 ? 1 : -1);
    window.setTimeout(() => { wheelLock.current = false; }, 520);
  }

  const selectedLabel = EXPERIENCE_MODE_OPTIONS.find((option) => option.id === value)?.label;

  return (
    <section
      className={styles.carousel}
      data-paused={motionPaused}
      data-autoplay-interval={autoPlayIntervalMs}
      aria-label={t("展示模式轮播")}
      onMouseEnter={() => setHoverPaused(true)}
      onMouseLeave={() => setHoverPaused(false)}
      onFocusCapture={() => setHoverPaused(true)}
      onBlurCapture={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setHoverPaused(false);
      }}
      onWheel={handleWheel}
    >
      <div className={styles.track} role="radiogroup" aria-label={t("选择展示模式")}>
        {EXPERIENCE_MODE_OPTIONS.map((option) => {
          const position = positionFor(option.id);
          const selected = position === "active";
          return (
            <article
              key={option.id}
              className={styles.card}
              data-mode={option.id}
              data-position={position}
              role="radio"
              aria-checked={selected}
              aria-label={`${option.label}：${option.description}`}
              tabIndex={selected ? 0 : -1}
              onClick={() => activateMode(option.id)}
              onKeyDown={(event) => handleCardKeyDown(event, option.id)}
            >
              <ExperienceModeDemo
                mode={option.id}
                avatarDisplayConfig={avatarDisplayConfig}
                avatarArtifactPreviewEnabled={avatarArtifactPreviewEnabled}
                compact
                active={selected && !motionPaused}
                reduceMotion={reduceMotion || prefersReducedMotion}
                voiceVisualTheme={voiceVisualTheme}
              />
              <span className={styles.shade} aria-hidden="true" />
              <span className={styles.number}>{MODE_META[option.id].number}</span>
              <div className={styles.copy}>
                <small>{t(option.description)}</small>
                <h2>{t(option.label)}</h2>
                <span>{MODE_META[option.id].action}<ArrowRight /></span>
              </div>
              <span className={styles.selected}><Check />{t("已选择")}</span>
            </article>
          );
        })}
      </div>

      <button className={`${styles.arrow} ${styles.previous}`} type="button" aria-label={t("上一个模式")} onClick={() => move(-1)}><ChevronLeft /></button>
      <button className={`${styles.arrow} ${styles.next}`} type="button" aria-label={t("下一个模式")} onClick={() => move(1)}><ChevronRight /></button>

      <div className={styles.start}>
        <VoiceStartButton connected={connected} onPress={() => onStartSession(value)} />
        {error && <small className="voice-session-start-error">{t(error)}</small>}
      </div>

      <footer className={styles.footer}>
        <div className={styles.dots} aria-label={t("轮播位置")}>
          {EXPERIENCE_MODE_OPTIONS.map((option) => (
            <button
              key={option.id}
              type="button"
              aria-label={t("选择") + (option.label) + ""}
              data-active={value === option.id}
              onClick={() => onChange(option.id)}
            />
          ))}
        </div>
        <button
          type="button"
          className={styles.pause}
          aria-pressed={manualPause}
          disabled={reduceMotion || prefersReducedMotion}
          onClick={() => setManualPause((paused) => !paused)}
        >
          {manualPause ? <Play /> : <Pause />}
          {reduceMotion || prefersReducedMotion ? t("已减少动态") : manualPause ? t("继续轮播") : t("暂停轮播")}
        </button>
        <p>{t("当前选择：")}<strong>{selectedLabel}</strong></p>
      </footer>
    </section>
  );
}

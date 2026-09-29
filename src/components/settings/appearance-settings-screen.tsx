"use client";
import { useLanguage } from "@/components/language/language-provider";


import { LanguageSelect } from "@/components/language/language-select";
import { Check } from "lucide-react";
import { useEffect, useState, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { useAppTheme } from "@/components/theme/app-theme-provider";
import { Orb } from "@/components/call/orb";
import { isVoiceVisualTheme, VOICE_VISUAL_THEME_OPTIONS, type VoiceVisualTheme } from "@/components/call/voice-theme";
import { APP_THEME_OPTIONS } from "@/lib/app-theme";
import {
  DEFAULT_WORKBENCH_VISUAL_PREFERENCES,
  readWorkbenchVisualPreferences,
  writeWorkbenchVisualPreferences,
} from "@/lib/workbench-visual-preferences";
import styles from "./appearance-settings-screen.module.css";

export function AppearanceSettingsScreen() {
  const { t } = useLanguage();
  const { theme, setTheme } = useAppTheme();
  const [orb, setOrb] = useState<VoiceVisualTheme>("cloud");
  const [previewState, setPreviewState] = useState<"listening" | "speaking">("listening");
  const [reducedMotion, setReducedMotion] = useState(false);
  const [visual, setVisual] = useState(DEFAULT_WORKBENCH_VISUAL_PREFERENCES);

  useEffect(() => {
    const savedOrb = window.localStorage.getItem("voice-agent-visual-theme");
    if (isVoiceVisualTheme(savedOrb)) setOrb(savedOrb);
    setReducedMotion(window.localStorage.getItem("voice-agent-reduced-motion") === "true");
    setVisual(readWorkbenchVisualPreferences());
  }, []);

  function updateVisual(next: typeof visual) {
    setVisual(next);
    writeWorkbenchVisualPreferences(next);
  }

  const selectedOrb = VOICE_VISUAL_THEME_OPTIONS.find((option) => option.id === orb) ?? VOICE_VISUAL_THEME_OPTIONS[0];
  const showcaseColors = {
    "--orb-accent-a": selectedOrb.colors[0],
    "--orb-accent-b": selectedOrb.colors[1],
    "--orb-accent-c": selectedOrb.colors[2],
  } as CSSProperties;

  function selectOrb(value: VoiceVisualTheme) {
    setOrb(value);
    window.localStorage.setItem("voice-agent-visual-theme", value);
  }

  function handleOrbArrowKey(event: ReactKeyboardEvent<HTMLDivElement>) {
    const direction = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1
      : event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 0;
    if (!direction) return;
    event.preventDefault();
    const index = VOICE_VISUAL_THEME_OPTIONS.findIndex((option) => option.id === orb);
    const nextIndex = (index + direction + VOICE_VISUAL_THEME_OPTIONS.length) % VOICE_VISUAL_THEME_OPTIONS.length;
    selectOrb(VOICE_VISUAL_THEME_OPTIONS[nextIndex].id);
    event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="radio"]')[nextIndex]?.focus();
  }

  return <div className={styles.page}>
    <h1 className={styles.pageTitle}>{t("外观")}</h1>
    <p className={styles.intro}>{t("这些偏好保存在当前浏览器，返回对话页后立即使用。")}</p>
    <section className={styles.section}><LanguageSelect /></section>
    <section className={styles.section}>
      <h2>{t("对话 Orb")}</h2><p>{t("选择纯对话模式的视觉效果，点击卡片即可预览并保存。")}</p>
      <details className={styles.disclosure}><summary>{t("预览效果")}</summary>
      <div className={styles.orbShowcase} style={showcaseColors} data-reduced-motion={reducedMotion}>
        <div className={styles.orbShowcaseTop}><span>{t("实时预览")}</span><span>{t("对话界面")}</span></div>
        <div className={styles.orbStage}><Orb state={previewState} level={previewState === "listening" ? 0.3 : 0.68} theme={orb} /></div>
        <div className={styles.orbShowcaseBottom}>
          <div><strong>{t(selectedOrb.name)}</strong><span>{t(selectedOrb.note)}</span></div>
          <div className={styles.previewStates} role="group" aria-label={t("预览对话状态")}>
            <button type="button" aria-pressed={previewState === "listening"} onClick={() => setPreviewState("listening")}>{t("聆听中")}</button>
            <button type="button" aria-pressed={previewState === "speaking"} onClick={() => setPreviewState("speaking")}>{t("回应中")}</button>
          </div>
        </div>
      </div>
      </details>
      <div className={styles.orbOptionGrid} role="radiogroup" aria-label={t("Orb 样式")} data-reduced-motion={reducedMotion} onKeyDown={handleOrbArrowKey}>
        {VOICE_VISUAL_THEME_OPTIONS.map((option) => <button
          className={styles.orbOption}
          key={option.id}
          type="button"
          role="radio"
          aria-checked={orb === option.id}
          data-selected={orb === option.id}
          tabIndex={orb === option.id ? 0 : -1}
          onClick={() => selectOrb(option.id)}
        >
          <span
            className={styles.orbOptionVisual}
            data-theme={option.id}
            style={{ "--orb-accent-a": option.colors[0], "--orb-accent-b": option.colors[1], "--orb-accent-c": option.colors[2] } as CSSProperties}
            aria-hidden="true"
          ><i /><i /><i /><i /><i /></span>
          <span className={styles.orbOptionInfo}><strong>{t(option.name)}</strong><small>{t(option.note)}</small></span>
          <span className={styles.orbOptionCheck} aria-hidden="true">{orb === option.id && <Check size={15} />}</span>
        </button>)}
      </div>
    </section>
    <section className={styles.section}>
      <h2>{t("界面主题")}</h2><p>{t("应用到导航、设置和资源页面。")}</p>
      <div className={styles.optionGrid} role="radiogroup" aria-label={t("界面主题")}>
        {APP_THEME_OPTIONS.map((option) => <button key={option.value} type="button" role="radio" aria-checked={theme === option.value} data-selected={theme === option.value} onClick={() => setTheme(option.value)}><span className={styles.swatches}>{option.colors.map((color) => <i key={color} style={{ background: color }} />)}</span><span>{t(option.label)}</span></button>)}
      </div>
    </section>
    <section className={styles.section}>
      <h2>{t("动态与玻璃效果")}</h2>
      <label className={styles.toggle}><span>{t("减少预览动态")}</span><input type="checkbox" checked={reducedMotion} onChange={(event) => { setReducedMotion(event.target.checked); window.localStorage.setItem("voice-agent-reduced-motion", String(event.target.checked)); }} /></label>
      <details className={styles.disclosure}><summary>{t("玻璃效果")}</summary>
      <label className={styles.range}><span>{t("全站玻璃透明度 ")}<strong>{visual.transparency}%</strong></span><input type="range" min="12" max="88" value={visual.transparency} onChange={(event) => updateVisual({ ...visual, transparency: Number(event.target.value) })} /></label>
      <label className={styles.range}><span>{t("全站玻璃模糊 ")}<strong>{visual.glassBlur}%</strong></span><input type="range" min="0" max="100" value={visual.glassBlur} onChange={(event) => updateVisual({ ...visual, glassBlur: Number(event.target.value) })} /></label>
      </details>
    </section>
  </div>;
}

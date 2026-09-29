"use client";
import { useLanguage } from "@/components/language/language-provider";


import Image from "next/image";
import { Pause, Play, UserRound } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type {
  AvatarDisplayConfig,
  ExperienceMode,
} from "@/components/digital-human/types";
import {
  AVATAR_IDENTITY_CHOICES,
  getLipSyncEffectPreview,
} from "@/components/digital-human/segmented-avatar-config";
import { Orb } from "./orb";
import type { VoiceVisualTheme } from "./voice-theme";

interface ExperienceModeDemoProps {
  mode: ExperienceMode;
  avatarDisplayConfig: AvatarDisplayConfig;
  avatarArtifactPreviewEnabled: boolean;
  compact?: boolean;
  active?: boolean;
  reduceMotion?: boolean;
  voiceVisualTheme?: VoiceVisualTheme;
}

const VOICE_VISUAL_THEME_LABELS: Record<VoiceVisualTheme, string> = {
  cloud: "云雾",
  "liquid-glass": "液态玻璃",
  "aurora-particles": "极光粒子",
  radial: "径向光盘",
  circle: "柔和圆形",
  bars: "音频柱",
  debug: "调试面板",
};

export function ExperienceModeDemo({
  mode,
  avatarDisplayConfig,
  avatarArtifactPreviewEnabled,
  compact = false,
  active = true,
  reduceMotion = false,
  voiceVisualTheme = "cloud",
}: ExperienceModeDemoProps) {
  const { t } = useLanguage();
  const [videoFailed, setVideoFailed] = useState(false);
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(true);
  const [playbackEnabled, setPlaybackEnabled] = useState(true);
  const selectedAvatar = useMemo(
    () => AVATAR_IDENTITY_CHOICES.find((choice) => choice.id === avatarDisplayConfig.segmentedPresetId)
      ?? AVATAR_IDENTITY_CHOICES[0],
    [avatarDisplayConfig.segmentedPresetId],
  );
  const effectPreview = getLipSyncEffectPreview(
    avatarDisplayConfig.segmentedPresetId,
    avatarDisplayConfig.segmentedVideoId,
    avatarDisplayConfig.segmentedLipSyncId,
  );
  const artifactId = effectPreview.kind === "video" ? effectPreview.artifactId : "";
  const motionActive = active && playbackEnabled && !reduceMotion && !prefersReducedMotion;
  const canPlayAvatar = mode === "avatar"
    && motionActive
    && avatarDisplayConfig.renderPath === "segmented"
    && avatarArtifactPreviewEnabled
    && !prefersReducedMotion
    && !videoFailed
    && Boolean(artifactId);
  const avatarImage: string | undefined = avatarDisplayConfig.renderPath === "hosted"
    ? avatarDisplayConfig.hostedAvatarImageUrl
    : selectedAvatar.imageUrl;
  const avatarName = avatarDisplayConfig.renderPath === "hosted" ? avatarDisplayConfig.hostedAvatarDisplayName ?? "当前数字人" : selectedAvatar.name;

  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setPrefersReducedMotion(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  useEffect(() => setVideoFailed(false), [artifactId]);

  const motionToggle = !compact && (
    <button
      type="button"
      className="mode-demo-motion-toggle"
      aria-pressed={motionActive}
      disabled={reduceMotion || prefersReducedMotion}
      onClick={() => setPlaybackEnabled((enabled) => !enabled)}
    >
      {motionActive ? <Pause /> : <Play />}
      {reduceMotion || prefersReducedMotion ? t("已减少动态") : motionActive ? t("暂停演示") : t("播放演示")}
    </button>
  );

  if (mode === "avatar") {
    return (
      <div className="mode-demo mode-demo-avatar" data-compact={compact} data-active={motionActive} aria-label={t("数字人模式动态演示")}>
        {motionToggle}
        {canPlayAvatar ? (
          <video
            key={artifactId}
            src={`/api/avatar-evaluation/artifacts/${artifactId}`}
            autoPlay
            muted
            loop
            playsInline
            preload="metadata"
            aria-label={"" + (avatarName) + t(" 口型动态演示")}
            onError={() => setVideoFailed(true)}
          />
        ) : avatarImage ? (
          <Image
            src={avatarImage}
            alt={"" + (avatarName) + t(" 数字人形象演示")}
            fill
            sizes={compact ? "50vw" : "(max-width: 900px) 92vw, 860px"}
            priority={!compact}
          />
        ) : <div className="mode-demo-avatar-placeholder">
          <UserRound aria-hidden="true" />
          <strong>{t(avatarName)}</strong>
          <small>{t("当前人物暂无可用静态预览")}</small>
        </div>}
        <span className="mode-demo-avatar-badge"><UserRound /> {avatarName.toUpperCase()}</span>
        <div className="mode-demo-avatar-copy">
          <span><i /> {canPlayAvatar ? "LIP SYNC DEMO" : "AVATAR PREVIEW"}</span>
          <strong>{t(avatarName)}</strong>
          <small>{t("切换形象与口型方案查看效果")}</small>
        </div>
      </div>
    );
  }

  return (
    <div
      className="mode-demo mode-demo-voice"
      data-compact={compact}
      data-active={motionActive}
      data-visual-theme={voiceVisualTheme}
      aria-label={t("对话模式") + (VOICE_VISUAL_THEME_LABELS[voiceVisualTheme]) + t("主题动态演示")}
    >
      {motionToggle}
      <div className="classic-preview-visual" aria-hidden="true">
        {motionActive ? (
          <Orb state="speaking" level={0.62} theme={voiceVisualTheme} />
        ) : (
          <span className="classic-theme-static" data-theme={voiceVisualTheme}>
            <i /><i /><i /><i /><i /><i /><i />
          </span>
        )}
      </div>
      <span className="classic-theme-label">{VOICE_VISUAL_THEME_LABELS[voiceVisualTheme]}</span>
      <div className="mode-demo-voice-copy">
        <span><i /> REALTIME VOICE</span>
        <strong>{t("自然开口，即刻回应")}</strong>
        <small>{t("视觉主题跟随聆听、思考与回复状态变化")}</small>
      </div>
    </div>
  );
}

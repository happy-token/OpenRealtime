import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { DEFAULT_AVATAR_DISPLAY_CONFIG } from "@/components/digital-human/types";
import { ConfigDrawer } from "@/components/drawer/config-drawer";
import { DEFAULT_TTS_VOICE } from "@/components/drawer/voice-options";
import { ExperienceModeDemo } from "./experience-mode-demo";
import { Orb } from "./orb";
import { isVoiceVisualTheme, type VoiceVisualTheme } from "./voice-theme";

function renderThemeDrawer(theme: VoiceVisualTheme) {
  return renderToStaticMarkup(
    <ConfigDrawer
      open
      onClose={() => {}}
      setBargeInMuted={() => {}}
      setNoiseSuppression={() => {}}
      setVolume={() => {}}
      sessionId={null}
      voiceVisualTheme={theme}
      onVoiceVisualThemeChange={() => {}}
      ttsVoice={DEFAULT_TTS_VOICE}
      ttsSpeechRate={0}
      ttsDialect=""
      ttsConfigurable
      ttsPreviewAvailable
      ttsConfigStatus=""
      onTtsVoiceChange={() => {}}
      onTtsSpeechRateChange={() => {}}
      onTtsDialectChange={() => {}}
      experienceMode="voice"
      onExperienceModeChange={() => {}}
      avatarDisplayConfig={DEFAULT_AVATAR_DISPLAY_CONFIG}
      onAvatarDisplayConfigChange={() => {}}
      avatarConfigLocked={false}
      avatarArtifactPreviewEnabled={false}
      reducedMotion={false}
      onReducedMotionChange={() => {}}
    />,
  );
}

describe("GitHub orb integrations", () => {
  it("accepts and offers both imported orb themes", () => {
    expect(isVoiceVisualTheme("liquid-glass")).toBe(true);
    expect(isVoiceVisualTheme("aurora-particles")).toBe(true);

    const liquidGlassHtml = renderThemeDrawer("liquid-glass");
    const auroraParticlesHtml = renderThemeDrawer("aurora-particles");

    expect(liquidGlassHtml).toContain('aria-label="语音视觉主题"');
    expect(liquidGlassHtml).toContain("液态玻璃");
    expect(auroraParticlesHtml).toContain('aria-label="语音视觉主题"');
    expect(auroraParticlesHtml).toContain("极光粒子");
  });

  it("renders the LerSent liquid-glass adapter through the shared orb interface", () => {
    const html = renderToStaticMarkup(
      <Orb state="speaking" level={0.72} theme="liquid-glass" />,
    );

    expect(html).toContain('data-orb-source="lersent001"');
    expect(html).toContain('data-state="speaking"');
    expect(html).toContain('data-level="0.720"');
    expect(html).toContain("<canvas");
  });

  it("renders the metasidd particle adapter and labels its preview", () => {
    const orbHtml = renderToStaticMarkup(
      <Orb state="listening" level={0.38} theme="aurora-particles" />,
    );
    const previewHtml = renderToStaticMarkup(
      <ExperienceModeDemo
        mode="voice"
        voiceVisualTheme="aurora-particles"
        avatarDisplayConfig={DEFAULT_AVATAR_DISPLAY_CONFIG}
        avatarArtifactPreviewEnabled={false}
      />,
    );

    expect(orbHtml).toContain('data-orb-source="metasidd"');
    expect(orbHtml).toContain('data-state="listening"');
    expect(orbHtml).toContain('data-level="0.380"');
    expect(previewHtml).toContain("极光粒子");
    expect(previewHtml).toContain("对话模式极光粒子主题动态演示");
  });
});

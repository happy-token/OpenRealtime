import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { DEFAULT_AVATAR_DISPLAY_CONFIG } from "@/components/digital-human/types";
import { ExperienceModeDemo } from "./experience-mode-demo";
import { ExperienceModeCarousel } from "./experience-mode-carousel";
import { ExperienceModeSwitch } from "./experience-mode-switch";
import { SessionControlBar } from "./session-control-bar";

describe("presentation mode display", () => {
  it("renders only the conversation and digital-human choices", () => {
    const html = renderToStaticMarkup(
      <ExperienceModeSwitch value="voice" onChange={() => {}} />,
    );

    expect(html).toContain("对话模式");
    expect(html).toContain("数字人模式");
    expect(html).not.toContain("聊天模式");
    expect(html).toContain('role="radiogroup"');
    expect(html).toContain('aria-checked="true"');
  });

  it("uses the selected avatar name without a hard-coded greeting", () => {
    const avatar = renderToStaticMarkup(
      <ExperienceModeDemo
        mode="avatar"
        avatarDisplayConfig={DEFAULT_AVATAR_DISPLAY_CONFIG}
        avatarArtifactPreviewEnabled
      />,
    );
    expect(avatar).toContain("Shuchang");
    expect(avatar).not.toContain("你好，我是");
    expect(avatar).not.toContain("固定 TTS 文本");
    expect(avatar).not.toContain("聊天模式");
  });

  it("renders the selected voice visual theme in the conversation preview", () => {
    const html = renderToStaticMarkup(
      <ExperienceModeDemo
        mode="voice"
        voiceVisualTheme="bars"
        avatarDisplayConfig={DEFAULT_AVATAR_DISPLAY_CONFIG}
        avatarArtifactPreviewEnabled={false}
      />,
    );

    expect(html).toContain('data-visual-theme="bars"');
    expect(html).toContain("音频柱");
    expect(html).toContain("对话模式音频柱主题动态演示");
  });

  it("uses a static themed preview when preview motion is reduced", () => {
    const html = renderToStaticMarkup(
      <ExperienceModeDemo
        mode="voice"
        voiceVisualTheme="radial"
        avatarDisplayConfig={DEFAULT_AVATAR_DISPLAY_CONFIG}
        avatarArtifactPreviewEnabled={false}
        reduceMotion
      />,
    );

    expect(html).toContain('class="classic-theme-static" data-theme="radial"');
    expect(html).not.toContain("实时语音状态可视化");
  });

  it("never borrows the Shuchang image for another avatar identity", () => {
    for (const segmentedPresetId of ["custom-upload", "liteavatar-preset", "dh-live-preset"]) {
      const html = renderToStaticMarkup(
        <ExperienceModeDemo
          mode="avatar"
          avatarDisplayConfig={{
            ...DEFAULT_AVATAR_DISPLAY_CONFIG,
            renderPath: "segmented",
            segmentedPresetId,
          }}
          avatarArtifactPreviewEnabled={false}
        />,
      );

      expect(html).toContain("当前人物暂无可用静态预览");
      expect(html).not.toContain("%2Fdigital-human%2Fshuchang-preview.jpg");
    }
  });

  it("renders the cinematic selector with a configurable autoplay interval", () => {
    const html = renderToStaticMarkup(
      <ExperienceModeCarousel
        value="voice"
        onChange={() => {}}
        avatarDisplayConfig={DEFAULT_AVATAR_DISPLAY_CONFIG}
        avatarArtifactPreviewEnabled={false}
        connected
        onStartSession={() => {}}
        error={null}
        autoPlayIntervalMs={6800}
      />,
    );

    expect(html).toContain('aria-label="展示模式轮播"');
    expect(html).toContain('data-autoplay-interval="6800"');
    expect(html).toContain('aria-label="对话模式：视觉主题与实时声场"');
    expect(html).toContain('aria-checked="true"');
    expect(html).toContain("已减少动态");
  });

  it("uses page-form controls instead of presentation switching during a session", () => {
    const html = renderToStaticMarkup(
      <SessionControlBar
        pageForm="fullscreen"
        paused={false}
        captionsEnabled
        onPageFormChange={() => {}}
        onCaptionsChange={() => {}}
        onPauseToggle={() => {}}
        onOpenSettings={() => {}}
        onTerminate={() => {}}
        onSendText={() => true}
      />,
    );

    expect(html).not.toContain('aria-label="返回内容形态"');
    expect(html).toContain('aria-label="页面形态：全屏"');
    expect(html).toContain('data-tooltip="页面形态：全屏"');
    expect(html).toContain('data-tooltip="关闭麦克风"');
    expect(html).toContain('data-tooltip="会话设置"');
    expect(html).toContain('data-transparency="70"');
    expect(html).toContain('data-glass-blur="10"');
    expect(html).toContain("--session-surface-alpha:0.30");
    expect(html).toContain("对话与形象并排");
    expect(html).not.toContain("数字人模式");
  });
});

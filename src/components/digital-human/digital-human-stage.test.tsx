import { renderToStaticMarkup as renderMarkup } from "react-dom/server";
import type { ReactNode } from "react";
import { ProviderKeyGate } from "@/components/provider-key/provider-key-gate";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { DEFAULT_AVATAR_DISPLAY_CONFIG } from "./types";
import { DigitalHumanStage, rendererCanStartConversation, usesOwnedAvatarSourceImage } from "./digital-human-stage";

function renderToStaticMarkup(element: ReactNode) {
  return renderMarkup(<ProviderKeyGate>{element}</ProviderKeyGate>);
}

function renderStage(displayConfig = DEFAULT_AVATAR_DISPLAY_CONFIG) {
  return renderToStaticMarkup(
    <DigitalHumanStage
      state="idle"
      statusLabel="待命"
      currentTurnText=""
      displayConfig={displayConfig}
      setAvatarAudioSink={() => {}}
      captionsEnabled
    />,
  );
}

describe("DigitalHumanStage", () => {
  it("starts the conversation for live, preview, and graceful fallback renderers", () => {
    expect(rendererCanStartConversation("ready")).toBe(true);
    expect(rendererCanStartConversation("preview")).toBe(true);
    expect(rendererCanStartConversation("degraded")).toBe(true);
    expect(rendererCanStartConversation("connecting")).toBe(false);
    expect(rendererCanStartConversation("error")).toBe(false);
  });

  it("loads the current owned source image for an internal Avatar id", () => {
    expect(usesOwnedAvatarSourceImage({
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      renderPath: "segmented",
      segmentedAvatarId: "shuchang",
      segmentedAvatarActionId: "builtin:identity-static:shuchang",
    })).toBe(true);
  });

  it("mounts the Anam media surface only for the implemented hosted renderer", () => {
    const html = renderStage({ ...DEFAULT_AVATAR_DISPLAY_CONFIG, avatarProfileId: "anam-custom-1" });

    expect(html).toContain('id="anam-digital-human-video"');
    expect(html).not.toContain("ANAM · HOSTED");
    expect(html).toContain('data-surface="fullbleed"');
    expect(html).toContain('data-hosted-avatar-id="anam-custom-1"');
    expect(html).not.toContain("配置预览 · 普通音频继续使用");
  });

  it("uses the selected hosted avatar immediately while its live renderer connects", () => {
    const html = renderStage({
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      avatarProfileId: "anam-mia",
      hostedAvatarDisplayName: "Mia",
      hostedAvatarImageUrl: "/digital-human/opentalking/companion/preview.png",
    });

    expect(html).toContain("Mia 数字人形象");
    expect(html).toContain("%2Fdigital-human%2Fopentalking%2Fcompanion%2Fpreview.png");
    expect(html).not.toContain("%2Fdigital-human%2Fshuchang-preview.jpg");
  });

  it("does not render a hard-coded greeting while the avatar starts", () => {
    const html = renderStage(DEFAULT_AVATAR_DISPLAY_CONFIG);

    expect(html).toContain("正在准备数字人");
    expect(html).toContain('role="status"');
    expect(html).not.toContain("你好，我是");
  });

  it("does not silently mount Anam for a segmented renderer draft", () => {
    const html = renderStage({
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      renderPath: "segmented",
      segmentedAvatarActionId: "motion-base-1",
      surface: "stage",
    });

    expect(html).not.toContain('id="anam-digital-human-video"');
    expect(html).not.toContain("Wav2Lip 96 · SEGMENTED");
    expect(html).not.toContain("digital-human-provider-badge");
    expect(html).not.toContain("digital-human-renderer-status");
    expect(html).toContain('data-render-path="segmented"');
    expect(html).toContain('data-surface="stage"');
    expect(html).toContain('data-motion-base-id="motion-base-1"');
  });

  it("mounts the validated LiveTalking Wav2Lip surface for its prepared segmented asset", () => {
    const html = renderStage({
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      renderPath: "segmented",
      segmentedAvatarActionId: "builtin:liveportrait-optimized",
    });

    expect(html).toContain('aria-label="Wav2Lip 实时数字人画面"');
    expect(html).not.toContain('/api/avatar-renderers/dh-live/');
    expect(html).not.toContain('id="anam-digital-human-video"');
  });

  it("mounts the Wav2Lip surface for another motion asset without startup greeting", () => {
    const html = renderStage({
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      renderPath: "segmented",
      segmentedPresetId: "custom-upload",
      segmentedAvatarId: "anchor",
      segmentedAvatarActionId: "builtin:opentalking:anchor",
    });

    expect(html).toContain('aria-label="Wav2Lip 实时数字人画面"');
    expect(html).toContain("主播 数字人测试形象");
    expect(html).not.toContain("你好，我是");
  });

  it("uses the selected OpenTalking identity when segmented mode has no motion", () => {
    const html = renderStage({
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      renderPath: "segmented",
      segmentedPresetId: "custom-upload",
      segmentedAvatarId: "newscaster",
      segmentedAvatarActionId: "",
    });

    expect(html).toContain("%2Fdigital-human%2Fopentalking%2Fnewscaster%2Fpreview.png");
    expect(html).toContain("新闻主播 数字人测试形象");
    expect(html).not.toContain('data-motion-base-id=');
  });

  it("can hide transient captions without removing the live surface", () => {
    const html = renderToStaticMarkup(
      <DigitalHumanStage
        state="speaking"
        statusLabel="AI 回复中"
        currentTurnText="这段临时字幕应当隐藏"
        displayConfig={DEFAULT_AVATAR_DISPLAY_CONFIG}
        setAvatarAudioSink={() => {}}
        captionsEnabled={false}
      />,
    );

    expect(html).toContain('class="digital-human-call-stage"');
    expect(html).not.toContain("这段临时字幕应当隐藏");
  });

  it("does not show renderer implementation details during a conversation", () => {
    const source = readFileSync(new URL("./digital-human-stage.tsx", import.meta.url), "utf8");

    expect(source).not.toContain("OpenRealtime 对话 ·");
    expect(source).not.toContain("LiveTalking · Wav2Lip 实时口型");
  });
});

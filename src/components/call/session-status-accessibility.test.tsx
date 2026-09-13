import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { DEFAULT_AVATAR_DISPLAY_CONFIG } from "@/components/digital-human/types";
import { DigitalHumanStage } from "@/components/digital-human/digital-human-stage";
import { CallView } from "./call-view";

const noop = () => {};

function renderVoiceStatus(theme: "cloud" | "bars") {
  return renderToStaticMarkup(
    <CallView
      hidden={false}
      sessionStarted
      state="listening"
      statusLabel="我在听"
      level={0}
      currentTurnText=""
      error={null}
      connected
      onStartSession={noop}
      visualTheme={theme}
      onVisualThemeChange={noop}
      experienceMode="voice"
      onExperienceModeChange={noop}
      avatarDisplayConfig={DEFAULT_AVATAR_DISPLAY_CONFIG}
      onAvatarDisplayConfigChange={noop}
      ttsProvider="doubao"
      ttsVoice="test"
      settingsRequest={0}
      renderAdvancedSettings={() => null}
      setAvatarAudioSink={noop}
      reducedMotion={false}
    />,
  );
}

describe("session status accessibility", () => {
  it.each(["cloud", "bars"] as const)("announces the %s Orb status without exposing its decorative dot", (theme) => {
    const html = renderVoiceStatus(theme);

    expect(html).toContain('role="status" aria-live="polite" aria-atomic="true"');
    expect(html).toContain('<i aria-hidden="true"></i>我在听');
  });

  it("announces the digital-human state and keeps its indicator decorative", () => {
    const html = renderToStaticMarkup(
      <DigitalHumanStage
        state="listening"
        statusLabel="我在听"
        currentTurnText=""
        displayConfig={DEFAULT_AVATAR_DISPLAY_CONFIG}
        setAvatarAudioSink={noop}
      />,
    );

    expect(html).toContain('class="digital-human-state" role="status" aria-live="polite" aria-atomic="true"');
    expect(html).toContain('<i aria-hidden="true"></i>我在听');
  });
});

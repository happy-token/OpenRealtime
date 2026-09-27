import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { SessionExperienceLayout } from "./session-experience-layout";

describe("SessionExperienceLayout", () => {
  it("shows conversation beside the surface in Sidecar and hides history in Fullscreen", () => {
    const sidecar = renderToStaticMarkup(
      <SessionExperienceLayout
        pageForm="sidecar"
        ambientColor="rgb(32 72 112)"
        surface={<div>ORB SURFACE</div>}
        conversation={<div>CONVERSATION HISTORY</div>}
        controls={<div>SESSION CONTROLS</div>}
        onEnterFullscreen={() => {}}
      />,
    );
    const fullscreen = renderToStaticMarkup(
      <SessionExperienceLayout
        pageForm="fullscreen"
        surface={<div>ORB SURFACE</div>}
        conversation={<div>CONVERSATION HISTORY</div>}
        controls={<div>SESSION CONTROLS</div>}
        onEnterFullscreen={() => {}}
      />,
    );

    expect(sidecar).toContain('aria-label="实时展示"');
    expect(sidecar).toContain("--session-avatar-ambient:rgb(32 72 112)");
    expect(sidecar).toContain('aria-label="对话内容" aria-hidden="false"');
    expect(sidecar).toContain('class="session-controls-region" aria-label="会话操作"><div>SESSION CONTROLS</div></div>');
    expect(sidecar).toContain('class="session-sidecar-resizer" role="separator" aria-label="调整对话区宽度"');
    expect(sidecar).not.toContain('aria-label="小窗显示控制"');
    expect(sidecar).not.toContain('class="session-surface-fullscreen"');
    expect(fullscreen).toContain('aria-label="对话内容" aria-hidden="true"');
    expect(fullscreen).not.toContain('aria-label="小窗显示控制"');
  });

  it("keeps the content companion itself as the fullscreen shortcut", () => {
    const html = renderToStaticMarkup(
      <SessionExperienceLayout
        pageForm="content"
        surface={<div>AVATAR</div>}
        surfaceOverlay={<div>ENDED ACTIONS</div>}
        conversation={<div>CONVERSATION</div>}
        controls={<div>SESSION CONTROLS</div>}
        onEnterFullscreen={() => {}}
      />,
    );

    expect(html).toContain('data-clickable="true"');
    expect(html).toContain('tabindex="0"');
    expect(html).toContain('role="toolbar" aria-label="小窗显示控制"');
    expect(html).toContain('aria-label="移动小窗"');
    expect(html).toContain('aria-label="最小化小窗"');
    expect(html).toContain('aria-label="全屏展示"');
    expect(html).toContain('class="session-content-stage-overlay"><div>ENDED ACTIONS</div></div>');
    expect(html.indexOf("ENDED ACTIONS")).toBeGreaterThan(html.indexOf('aria-label="实时展示"'));
  });

  it("removes the control bar from the ended layout", () => {
    const html = renderToStaticMarkup(<SessionExperienceLayout
      pageForm="fullscreen"
      surface={<div>AVATAR</div>}
      surfaceOverlay={<div>ENDED ACTIONS</div>}
      conversation={<div>CONVERSATION</div>}
      onEnterFullscreen={() => {}}
    />);
    expect(html).toContain("ENDED ACTIONS");
    expect(html).not.toContain('aria-label="会话操作"');
  });
});

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { SessionExperienceLayout } from "./session-experience-layout";

describe("SessionExperienceLayout", () => {
  it("shows conversation beside the surface in Sidecar and hides history in Fullscreen", () => {
    const sidecar = renderToStaticMarkup(
      <SessionExperienceLayout
        pageForm="sidecar"
        surface={<div>ORB SURFACE</div>}
        conversation={<div>CONVERSATION HISTORY</div>}
        onEnterFullscreen={() => {}}
      />,
    );
    const fullscreen = renderToStaticMarkup(
      <SessionExperienceLayout
        pageForm="fullscreen"
        surface={<div>ORB SURFACE</div>}
        conversation={<div>CONVERSATION HISTORY</div>}
        onEnterFullscreen={() => {}}
      />,
    );

    expect(sidecar).toContain('aria-label="实时展示"');
    expect(sidecar).toContain('aria-label="对话内容" aria-hidden="false"');
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
        conversation={<div>CONVERSATION</div>}
        onEnterFullscreen={() => {}}
      />,
    );

    expect(html).toContain('data-clickable="true"');
    expect(html).toContain('tabindex="0"');
    expect(html).toContain('role="toolbar" aria-label="小窗显示控制"');
    expect(html).toContain('aria-label="移动小窗"');
    expect(html).toContain('aria-label="最小化小窗"');
    expect(html).toContain('aria-label="全屏展示"');
  });
});

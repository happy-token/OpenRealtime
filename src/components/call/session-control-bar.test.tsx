import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { SessionControlBar } from "./session-control-bar";

const handlers = {
  onPageFormChange: () => {},
  onCaptionsChange: () => {},
  onPauseToggle: () => {},
  onOpenSettings: () => {},
  onTerminate: () => {},
  onSendText: () => true,
  assistantBusy: false,
  onStopReply: () => {},
};

describe("SessionControlBar ended state", () => {
  it("keeps the original layout control and retires inactive buttons in place", () => {
    const html = renderToStaticMarkup(<SessionControlBar
      pageForm="fullscreen"
      paused
      captionsEnabled
      ended
      {...handlers}
    />);
    expect(html).toContain('data-ended="true"');
    expect(html).toContain('aria-label="页面形态：全屏"');
    expect(html.match(/data-retire-on-end="true"/g)).toHaveLength(5);
    expect(html.match(/aria-hidden="true"/g)?.length).toBeGreaterThanOrEqual(5);
    expect(html).not.toContain('aria-label="输入对话消息"');
  });
});


describe("SessionControlBar active semantics", () => {
  it("uses the keyboard control to focus persistent inputs outside fullscreen", () => {
    const sidecar = renderToStaticMarkup(<SessionControlBar pageForm="sidecar" paused={false} captionsEnabled {...handlers} />);
    const fullscreen = renderToStaticMarkup(<SessionControlBar pageForm="fullscreen" paused={false} captionsEnabled {...handlers} />);

    expect(sidecar).toContain('aria-label="聚焦文字输入"');
    expect(sidecar).not.toContain('aria-label="展开文字输入"');
    expect(fullscreen).toContain('aria-label="展开文字输入"');
  });

  it("only exposes stop reply while the assistant is busy", () => {
    const idle = renderToStaticMarkup(<SessionControlBar pageForm="fullscreen" paused={false} captionsEnabled {...handlers} />);
    const busy = renderToStaticMarkup(<SessionControlBar pageForm="fullscreen" paused={false} captionsEnabled {...handlers} assistantBusy />);

    expect(idle).not.toContain('aria-label="停止回复"');
    expect(busy).toContain('aria-label="停止回复"');
  });
});

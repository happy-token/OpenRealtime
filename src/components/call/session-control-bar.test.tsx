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

describe("SessionControlBar active semantics", () => {
  it("shows layout controls during an active call", () => {
    const html = renderToStaticMarkup(<SessionControlBar pageForm="fullscreen" paused captionsEnabled {...handlers} />);
    expect(html).toContain('aria-label="页面形态：全屏"');
  });
  it("uses the keyboard control to focus persistent inputs outside fullscreen", () => {
    const sidecar = renderToStaticMarkup(<SessionControlBar pageForm="sidecar" paused={false} captionsEnabled {...handlers} />);
    const fullscreen = renderToStaticMarkup(<SessionControlBar pageForm="fullscreen" paused={false} captionsEnabled {...handlers} />);

    expect(sidecar).toContain('aria-label="聚焦文字输入"');
    expect(sidecar).not.toContain('aria-label="展开文字输入"');
    expect(fullscreen).toContain('aria-label="展开文字输入"');
  });

  it("keeps stop reply out of the bar even while the assistant is busy", () => {
    const idle = renderToStaticMarkup(<SessionControlBar pageForm="fullscreen" paused={false} captionsEnabled {...handlers} />);
    const busy = renderToStaticMarkup(<SessionControlBar pageForm="fullscreen" paused={false} captionsEnabled {...handlers} assistantBusy />);

    expect(idle).not.toContain('aria-label="停止回复"');
    expect(busy).not.toContain('aria-label="停止回复"');
  });
});

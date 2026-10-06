import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { SessionControlBar } from "./session-control-bar";

const handlers = {
  onPageFormChange: () => {},
  onCaptionsChange: () => {},
  onPauseToggle: () => {},
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
  it.each(["sidecar", "content"] as const)("does not duplicate the persistent input in %s", (pageForm) => {
    const html = renderToStaticMarkup(<SessionControlBar pageForm={pageForm} paused={false} captionsEnabled {...handlers} />);
    const fullscreen = renderToStaticMarkup(<SessionControlBar pageForm="fullscreen" paused={false} captionsEnabled {...handlers} />);

    expect(html).toContain('aria-label="输入对话消息"');
    expect(html).toContain('aria-label="发送消息"');
    expect(html).not.toContain('aria-label="聚焦文字输入"');
    expect(html).not.toContain('aria-label="展开文字输入"');
    expect(fullscreen).toContain('aria-label="展开文字输入"');
  });

  it.each([true, false])("keeps only useful sidecar actions with captions=%s", (captionsEnabled) => {
    const html = renderToStaticMarkup(<SessionControlBar pageForm="sidecar" paused={false} captionsEnabled={captionsEnabled} {...handlers} />);
    expect(html).not.toContain('aria-label="会话设置"');
    expect(html).not.toContain('aria-label="隐藏临时字幕"');
    expect(html).not.toContain('aria-label="显示临时字幕"');
    expect(html).toContain('aria-label="关闭麦克风"');
    expect(html).toContain('aria-label="页面形态：并排"');
    expect(html).toContain('aria-label="结束通话"');
  });

  it.each(["fullscreen", "sidecar", "content"] as const)("shows captions only in fullscreen, without settings, in %s", (pageForm) => {
    const html = renderToStaticMarkup(<SessionControlBar pageForm={pageForm} paused={false} captionsEnabled {...handlers} />);
    expect(html).not.toContain('aria-label="会话设置"');
    if (pageForm === "fullscreen") expect(html).toContain('aria-label="隐藏临时字幕"');
    else expect(html).not.toContain('aria-label="隐藏临时字幕"');
  });

  it("keeps stop reply out of the bar even while the assistant is busy", () => {
    const idle = renderToStaticMarkup(<SessionControlBar pageForm="fullscreen" paused={false} captionsEnabled {...handlers} />);
    const busy = renderToStaticMarkup(<SessionControlBar pageForm="fullscreen" paused={false} captionsEnabled {...handlers} assistantBusy />);

    expect(idle).not.toContain('aria-label="停止回复"');
    expect(busy).not.toContain('aria-label="停止回复"');
  });
});

it.each(["fullscreen", "sidecar", "content"] as const)("omits session settings in %s", (pageForm) => {
  const html = renderToStaticMarkup(<SessionControlBar {...handlers} paused={false} captionsEnabled pageForm={pageForm} />);
  expect(html).not.toContain('aria-label="会话设置"');
  expect(html).not.toContain('data-tooltip="会话设置"');
});

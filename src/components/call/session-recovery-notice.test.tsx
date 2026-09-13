import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { resolveSessionRecoveryIssue, SessionRecoveryNotice } from "./session-recovery-notice";

const handlers = { onRetryConnection: () => {}, onRetryMicrophone: () => {}, onUseText: () => {} };

describe("SessionRecoveryNotice", () => {
  it("prioritizes a disconnected session and preserves a text route", () => {
    const html = renderToStaticMarkup(<SessionRecoveryNotice connection="error" micError="麦克风错误：拒绝访问" micAvailable={false} sessionError={null} {...handlers} />);
    expect(html).toContain("连接未恢复");
    expect(html).toContain("请重试连接或改用文字");
    expect(html).toContain("重试连接");
    expect(html).toContain("改用文字");
  });

  it("shows a microphone retry while the transport remains usable", () => {
    const issue = resolveSessionRecoveryIssue({ connection: "open", micError: "麦克风错误：权限被拒绝", micAvailable: true, sessionError: null });
    expect(issue).toMatchObject({ kind: "microphone", retry: "microphone" });
    const html = renderToStaticMarkup(<SessionRecoveryNotice connection="open" micError="麦克风错误：权限被拒绝" micAvailable sessionError={null} {...handlers} />);
    expect(html).toContain("权限被拒绝");
    expect(html).not.toContain("麦克风错误：权限被拒绝");
  });

  it("stays hidden for a healthy session", () => {
    expect(renderToStaticMarkup(<SessionRecoveryNotice connection="open" micError={null} micAvailable sessionError={null} {...handlers} />)).toBe("");
  });
});

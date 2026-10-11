import { renderToStaticMarkup } from "react-dom/server";
import { expect, it, vi } from "vitest";
import { SessionDiagnostics } from "./session-diagnostics";
import type { SessionDiagnosticsReport } from "@/lib/session-diagnostics-report";
vi.mock("@/components/workspace/workspace-shell", () => ({ WorkspaceShell: ({ children }: { children: React.ReactNode }) => children }));
vi.mock("@/components/language/language-provider", () => ({ useLanguage: () => ({ t: (text: string) => text }), LocalizedText: ({ text }: { text: React.ReactNode }) => text }));
it("renders remaining logs without crashing when telemetry is unavailable", () => {
  const report: SessionDiagnosticsReport = { schema_version: 1, session_id: "test", telemetry: null, conversation: [], debug_log: { voice_session_id: "test", entries: [] }, audio: { status: "not-configured" }, sources: { telemetry: { status: "unavailable", truncated: false }, conversation: { status: "available", truncated: false }, debug_log: { status: "available", truncated: false } } };
  const html = renderToStaticMarkup(<SessionDiagnostics sessionId="test" preview={report} />);
  expect(html).toContain("会话详情");
  expect(html).toContain("无法确认此会话是否已录音");
  expect(html).not.toContain("该策略尚未启用");
  expect(html).toContain("没有记录或数据源不可用");
  expect(html).toContain("生成 Agent 只读凭据");
  expect(html).toContain("预览页面不签发凭据。");
  expect(html).toMatch(/<button disabled="">生成 Agent 只读凭据<\/button>/);
});

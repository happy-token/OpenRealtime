import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { ConversationSessionLink } from "./conversation-detail-screen";
describe("conversation Session ID link", () => {
  it("links an administrator to the corresponding diagnostic session", () => {
    const html = renderToStaticMarkup(<ConversationSessionLink sessionId="session-123" canViewDiagnostics />);
    expect(html).toContain('href="/settings/session-diagnostics/sessions/session-123"');
    expect(html).toContain("Session ID");
    expect(html).toContain("session-123");
  });
  it("renders no identifier or link for a non-administrator", () => {
    expect(renderToStaticMarkup(<ConversationSessionLink sessionId="session-123" canViewDiagnostics={false} />)).toBe("");
  });
  it("does not invent a Session ID for records without one", () => {
    expect(renderToStaticMarkup(<ConversationSessionLink canViewDiagnostics />)).toBe("");
  });
});

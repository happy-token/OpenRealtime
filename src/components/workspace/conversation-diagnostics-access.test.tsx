import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
const mocks = vi.hoisted(() => ({ user: vi.fn(), admin: vi.fn() }));
vi.mock("next/headers", () => ({ headers: async () => new Headers() }));
vi.mock("@/lib/user-session", () => ({ userFromRequest: mocks.user }));
vi.mock("@/lib/app-admin-accounts", () => ({ isAppAdmin: mocks.admin }));
vi.mock("@/components/workspace/workspace-shell", () => ({ WorkspaceShell: ({ children }: { children: React.ReactNode }) => children }));
vi.mock("@/components/workspace/conversation-detail-screen", () => ({ ConversationDetailScreen: ({ id, canViewDiagnostics }: { id: string; canViewDiagnostics: boolean }) => <span data-diagnostics={String(canViewDiagnostics)}>{id}</span> }));
import ConversationPage from "@/app/conversations/[conversationId]/page";
describe("conversation diagnostics permission", () => {
  beforeEach(() => vi.resetAllMocks());
  it.each([true, false])("passes the server-verified administrator grant: %s", async grant => {
    const user = { issuer: "sso", subject: "account" };
    mocks.user.mockResolvedValue(user);
    mocks.admin.mockResolvedValue(grant);
    const html = renderToStaticMarkup(await ConversationPage({ params: Promise.resolve({ conversationId: "conversation-1" }) }));
    expect(html).toContain(`data-diagnostics="${grant}"`);
    expect(mocks.admin).toHaveBeenCalledWith(user);
  });
  it("does not grant anonymous users access", async () => {
    mocks.user.mockResolvedValue(null);
    const html = renderToStaticMarkup(await ConversationPage({ params: Promise.resolve({ conversationId: "conversation-1" }) }));
    expect(html).toContain('data-diagnostics="false"');
    expect(mocks.admin).not.toHaveBeenCalled();
  });
});

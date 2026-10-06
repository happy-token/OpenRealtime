import { expect, it, vi } from "vitest";
import AdminPage from "@/app/admin/page";
import SessionPage from "@/app/admin/sessions/[sessionId]/page";

vi.mock("next/navigation", () => ({
  redirect: (path: string) => { throw new Error(`redirect:${path}`); },
}));

it("redirects the legacy overview to settings", () => {
  expect(() => AdminPage()).toThrow("redirect:/settings/session-diagnostics");
});

it("preserves the session ID when redirecting a legacy detail link", async () => {
  await expect(SessionPage({ params: Promise.resolve({ sessionId: "session-123" }) }))
    .rejects.toThrow("redirect:/settings/session-diagnostics/sessions/session-123");
});

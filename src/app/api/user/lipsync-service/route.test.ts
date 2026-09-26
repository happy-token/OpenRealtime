import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/user-session", () => ({ userFromRequest: vi.fn() }));
vi.mock("@/lib/avatar-test-access", () => ({ isSameOriginAvatarMutation: vi.fn(() => true) }));
vi.mock("@/lib/user-lipsync-service", () => ({
  loadUserLipsyncService: vi.fn(), saveUserLipsyncService: vi.fn(), deleteUserLipsyncService: vi.fn(),
  probeUserLipsyncService: vi.fn(), normalizePersonalLipsyncUrl: vi.fn((url: string) => url),
  normalizePersonalLipsyncToken: vi.fn((token: string) => token),
}));

import { isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import { userFromRequest } from "@/lib/user-session";
import { loadUserLipsyncService, probeUserLipsyncService } from "@/lib/user-lipsync-service";
import { GET, POST, PUT, DELETE } from "./route";

const request = (method: string) => new Request("https://realtime.example/api/user/lipsync-service", { method, ...(method === "PUT" ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url: "https://models.example" }) } : {}) });

describe("personal lip-sync service authorization", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(isSameOriginAvatarMutation).mockReturnValue(true);
    vi.mocked(userFromRequest).mockResolvedValue(null);
  });

  it("rejects every operation for an anonymous visitor", async () => {
    for (const [method, handler] of [["GET", GET], ["POST", POST], ["PUT", PUT], ["DELETE", DELETE]] as const) {
      expect((await handler(request(method))).status).toBe(401);
    }
  });

  it("rejects cross-origin mutations before reading credentials", async () => {
    vi.mocked(isSameOriginAvatarMutation).mockReturnValue(false);
    expect((await PUT(request("PUT"))).status).toBe(403);
    expect(userFromRequest).not.toHaveBeenCalled();
  });

  it("does not return a saved token, and reports failed readiness", async () => {
    vi.mocked(userFromRequest).mockResolvedValue({ issuer: "https://identity.example", subject: "alice" });
    vi.mocked(loadUserLipsyncService).mockResolvedValue({ url: "https://models.example", token: "secret" });
    vi.mocked(probeUserLipsyncService).mockResolvedValue(false);
    const status = await GET(request("GET"));
    expect(await status.text()).not.toContain("secret");
    expect((await POST(request("POST")).then((response) => response.json()) as { ready: boolean }).ready).toBe(false);
  });
});

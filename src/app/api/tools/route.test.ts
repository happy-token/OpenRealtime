import { beforeEach, describe, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({ admin: vi.fn(), user: vi.fn(), list: vi.fn() }));
vi.mock("@/lib/avatar-assets-server", () => ({ authorizeAvatarAssetRequest: mocked.admin, jsonError: (error: string, status: number) => Response.json({ error }, { status }) }));
vi.mock("@/lib/user-session", () => ({ userFromRequest: mocked.user }));
vi.mock("@/lib/tool-catalog-repository", () => ({ listTools: mocked.list, createTool: vi.fn() }));

import { GET } from "./route";

beforeEach(() => {
  vi.clearAllMocks();
  mocked.admin.mockReturnValue(false);
  mocked.user.mockResolvedValue({ issuer: "test", subject: "alice" });
  mocked.list.mockResolvedValue([
    { tool_id: "tool-current-time", builtin: true, enabled: true, endpoint: null },
    { tool_id: "private", builtin: false, public_enabled: false, endpoint: "https://private.example" },
    { tool_id: "public", builtin: false, public_enabled: true, endpoint: "https://public.example" },
  ]);
});

describe("tool catalog visibility", () => {
  it("gives signed-in users built-ins and public tools without endpoint details", async () => {
    const response = await GET(new Request("http://localhost/api/tools"));
    expect(response.status).toBe(200);
    expect((await response.json()).tools).toEqual([
      { tool_id: "tool-current-time", builtin: true, enabled: true, endpoint: null },
      { tool_id: "public", builtin: false, public_enabled: true, endpoint: null },
    ]);
  });

  it("rejects anonymous users and retains full admin visibility", async () => {
    mocked.user.mockResolvedValue(null);
    expect((await GET(new Request("http://localhost/api/tools"))).status).toBe(403);
    mocked.admin.mockReturnValue(true);
    const response = await GET(new Request("http://localhost/api/tools"));
    expect((await response.json()).tools).toHaveLength(3);
    expect(mocked.user).toHaveBeenCalledTimes(1);
  });
});

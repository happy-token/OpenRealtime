import { afterEach, describe, expect, it, vi } from "vitest";

const repository = vi.hoisted(() => ({ setDeletion: vi.fn(), rename: vi.fn() }));
vi.mock("@/lib/avatar-catalog-repository", () => ({ setTalkingVariantDeletion: repository.setDeletion, renameTalkingVariant: repository.rename }));

import { PATCH } from "./route";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

function request(operation: string, origin = "http://127.0.0.1:3010", displayName?: unknown) {
  return new Request("http://127.0.0.1:3010/api/avatars/avatar-123/actions/base/talking-variants/talk-1", {
    method: "PATCH",
    headers: { origin, host: "127.0.0.1:3010", "sec-fetch-site": "same-origin", "content-type": "application/json" },
    body: JSON.stringify({ operation, displayName }),
  });
}

const context = { params: Promise.resolve({ avatarId: "avatar-123", avatarActionId: "base", variantId: "talk-1" }) };

describe("Talking material update route", () => {
  it("deletes an owned variant with same-origin authorization", async () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("AVATAR_LOCAL_TEST_MODE", "true");
    vi.stubEnv("AVATAR_EVALUATION_LOOPBACK_BOUND", "true");
    repository.setDeletion.mockResolvedValue({ avatar_action_id: "base", talking_variants: [] });
    const response = await PATCH(request("trash"), context);
    expect(response.status).toBe(200);
    expect(repository.setDeletion).toHaveBeenCalledWith("avatar-123", "base", "talk-1", true);
  });

  it("rejects invalid operations and cross-origin requests", async () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("AVATAR_LOCAL_TEST_MODE", "true");
    vi.stubEnv("AVATAR_EVALUATION_LOOPBACK_BOUND", "true");
    expect((await PATCH(request("remove"), context)).status).toBe(400);
    expect((await PATCH(request("trash", "https://elsewhere.example"), context)).status).toBe(403);
    expect(repository.setDeletion).not.toHaveBeenCalled();
  });

  it("renames an owned material and rejects invalid names before mutation", async () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("AVATAR_LOCAL_TEST_MODE", "true");
    vi.stubEnv("AVATAR_EVALUATION_LOOPBACK_BOUND", "true");
    repository.rename.mockResolvedValue({ avatar_action_id: "base", talking_variants: [{ id: "talk-1", display_name: "晨间版" }] });

    expect((await PATCH(request("rename", undefined, "  晨间版  "), context)).status).toBe(200);
    expect(repository.rename).toHaveBeenCalledWith("avatar-123", "base", "talk-1", "晨间版");
    repository.rename.mockClear();
    expect((await PATCH(request("rename", undefined, "   "), context)).status).toBe(400);
    expect((await PATCH(request("rename", undefined, "x".repeat(51)), context)).status).toBe(400);
    expect((await PATCH(request("rename", undefined, 42), context)).status).toBe(400);
    expect((await PATCH(request("rename", "https://elsewhere.example", "晨间版"), context)).status).toBe(403);
    expect(repository.rename).not.toHaveBeenCalled();
  });
});

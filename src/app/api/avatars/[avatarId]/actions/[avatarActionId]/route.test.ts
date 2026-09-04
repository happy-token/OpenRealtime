import { afterEach, describe, expect, it, vi } from "vitest";

const repository = vi.hoisted(() => ({ updateAction: vi.fn() }));

vi.mock("@/lib/avatar-catalog-repository", () => ({
  updateOwnedAvatarAction: repository.updateAction,
}));

import { PATCH } from "./route";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

function enableLocalTestMode() {
  vi.stubEnv("NODE_ENV", "development");
  vi.stubEnv("AVATAR_LOCAL_TEST_MODE", "true");
  vi.stubEnv("AVATAR_EVALUATION_LOOPBACK_BOUND", "true");
}

function patchRequest(body: object) {
  return new Request("http://127.0.0.1:3010/api/avatars/avatar-123/actions/action-1", {
    method: "PATCH",
    headers: {
      host: "127.0.0.1:3010",
      origin: "http://127.0.0.1:3010",
      "sec-fetch-site": "same-origin",
      "content-type": "application/json",
    },
    body: JSON.stringify(body),
  });
}

const context = { params: Promise.resolve({ avatarId: "avatar-123", avatarActionId: "action-1" }) };

describe("Avatar action update route", () => {
  it("renames an action from a same-origin request", async () => {
    enableLocalTestMode();
    repository.updateAction.mockResolvedValue({ avatar_action_id: "action-1", display_name: "温柔回应" });

    const response = await PATCH(patchRequest({ operation: "rename", displayName: "温柔回应" }), context);

    expect(response.status).toBe(200);
    expect(repository.updateAction).toHaveBeenCalledWith("avatar-123", "action-1", { displayName: "温柔回应" });
    await expect(response.json()).resolves.toMatchObject({ action: { display_name: "温柔回应" } });
  });

  it("rejects a rename without a nonblank string name", async () => {
    enableLocalTestMode();

    const response = await PATCH(patchRequest({ operation: "rename", displayName: "   " }), context);

    expect(response.status).toBe(400);
    expect(repository.updateAction).not.toHaveBeenCalled();
  });
});

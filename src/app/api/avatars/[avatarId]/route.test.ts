import { afterEach, describe, expect, it, vi } from "vitest";

const repository = vi.hoisted(() => ({
  find: vi.fn(),
  replaceSourceImage: vi.fn(),
  update: vi.fn(),
}));

vi.mock("@/lib/avatar-catalog-repository", () => ({
  findOwnedAvatar: repository.find,
  replaceOwnedAvatarSourceImage: repository.replaceSourceImage,
  updateOwnedAvatar: repository.update,
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

function replacementRequest(body: object) {
  return new Request("http://127.0.0.1:3010/api/avatars/avatar-123", {
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

const context = { params: Promise.resolve({ avatarId: "avatar-123" }) };

describe("Avatar source image replacement route", () => {
  it("replaces the image with the user's action-retention choice", async () => {
    enableLocalTestMode();
    repository.replaceSourceImage.mockResolvedValue({
      avatar_id: "avatar-123",
      source_image_url: "/api/avatars/avatar-123/image",
      realtime_binding: null,
      actions: [],
    });

    const response = await PATCH(replacementRequest({
      operation: "replaceSourceImage",
      sourceImageDataUrl: "data:image/png;base64,iVBORw0KGgo=",
      trashActions: false,
    }), context);

    expect(response.status).toBe(200);
    expect(repository.replaceSourceImage).toHaveBeenCalledWith("avatar-123", {
      sourceImageDataUrl: "data:image/png;base64,iVBORw0KGgo=",
      trashActions: false,
    });
  });

  it("requires an explicit action-retention choice", async () => {
    enableLocalTestMode();
    const response = await PATCH(replacementRequest({
      operation: "replaceSourceImage",
      sourceImageDataUrl: "data:image/png;base64,iVBORw0KGgo=",
    }), context);

    expect(response.status).toBe(400);
    expect(repository.replaceSourceImage).not.toHaveBeenCalled();
  });

  it("renames an Avatar from a same-origin request", async () => {
    enableLocalTestMode();
    repository.update.mockResolvedValue({ avatar_id: "avatar-123", display_name: "小林", actions: [] });

    const response = await PATCH(replacementRequest({ operation: "rename", displayName: "小林" }), context);

    expect(response.status).toBe(200);
    expect(repository.update).toHaveBeenCalledWith("avatar-123", { displayName: "小林" });
    await expect(response.json()).resolves.toMatchObject({ avatar: { display_name: "小林" } });
  });

  it("rejects a blank Avatar name", async () => {
    enableLocalTestMode();

    const response = await PATCH(replacementRequest({ operation: "rename", displayName: "   " }), context);

    expect(response.status).toBe(400);
    expect(repository.update).not.toHaveBeenCalled();
  });

  it("rejects oversized replacement requests before parsing JSON", async () => {
    enableLocalTestMode();
    const request = replacementRequest({ operation: "replaceSourceImage" });
    request.headers.set("content-length", "6100001");

    const response = await PATCH(request, context);

    expect(response.status).toBe(413);
    expect(repository.replaceSourceImage).not.toHaveBeenCalled();
  });
});

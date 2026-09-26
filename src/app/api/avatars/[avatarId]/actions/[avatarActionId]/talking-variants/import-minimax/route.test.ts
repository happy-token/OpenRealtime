import { createHash } from "node:crypto";
import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const dependencies = vi.hoisted(() => ({
  findAvatar: vi.fn(), attach: vi.fn(), trusted: vi.fn(), source: vi.fn(),
  key: vi.fn(), fingerprint: vi.fn(), generation: vi.fn(), download: vi.fn(),
  mkdir: vi.fn(), writeFile: vi.fn(), unlink: vi.fn(),
}));
vi.mock("@/lib/avatar-catalog-repository", () => ({ findOwnedAvatar: dependencies.findAvatar, attachTalkingVariant: dependencies.attach }));
vi.mock("@/lib/ltx-task-coordinator", () => ({ getTrustedLocalLtxTask: dependencies.trusted }));
vi.mock("@/lib/musetalk-talking-worker", () => ({ readTalkingSource: dependencies.source }));
vi.mock("@/lib/provider-api-key", () => ({ resolveProviderApiKey: dependencies.key, providerKeyFingerprint: dependencies.fingerprint }));
vi.mock("@/lib/video-generation-provider", () => ({ getVideoGeneration: dependencies.generation }));
vi.mock("@/lib/ltx-result-video", () => ({ downloadLtxResultVideo: dependencies.download }));
vi.mock("node:fs/promises", () => ({ mkdir: dependencies.mkdir, writeFile: dependencies.writeFile, unlink: dependencies.unlink }));

import { POST } from "./route";

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllEnvs();
});

function request() {
  return new NextRequest("http://127.0.0.1:3010/api/avatars/avatar-123/actions/base/talking-variants/import-minimax", {
    method: "POST",
    headers: { host: "127.0.0.1:3010", origin: "http://127.0.0.1:3010", "sec-fetch-site": "same-origin", "content-type": "application/json" },
    body: JSON.stringify({ taskId: "provider-task-1" }),
  });
}
const context = { params: Promise.resolve({ avatarId: "avatar-123", avatarActionId: "base" }) };

describe("MiniMax talking material import", () => {
  it("saves only a trusted result created from the current action video", async () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("AVATAR_LOCAL_TEST_MODE", "true");
    vi.stubEnv("AVATAR_EVALUATION_LOOPBACK_BOUND", "true");
    const source = Buffer.from("source video");
    dependencies.findAvatar.mockResolvedValue({ avatar_id: "avatar-123", deleted_at: null, actions: [{ avatar_action_id: "base", display_name: "柔和回应", deleted_at: null, video_url: "/base.mp4" }] });
    dependencies.source.mockResolvedValue(source);
    dependencies.trusted.mockReturnValue({ visualIdentityId: "avatar-123", model: "MiniMax-H3", referenceVideoSha256: createHash("sha256").update(source).digest("hex"), credentialFingerprint: "fingerprint" });
    dependencies.key.mockResolvedValue("key");
    dependencies.fingerprint.mockReturnValue("fingerprint");
    dependencies.generation.mockResolvedValue({ state: "success", videoUrl: "https://example.com/result.mp4" });
    dependencies.download.mockResolvedValue({ mediaType: "video/mp4", bytes: new Uint8Array([0, 0, 0, 24]) });
    dependencies.attach.mockImplementation(async (_avatarId, _actionId, variant) => ({ avatar_action_id: "base", talking_variants: [variant] }));

    const response = await POST(request(), context);
    expect(response.status).toBe(200);
    expect(dependencies.attach).toHaveBeenCalledWith("avatar-123", "base", expect.objectContaining({ method: "minimax", source_video_url: "/base.mp4" }));
    expect(dependencies.writeFile).toHaveBeenCalledOnce();
  });

  it("rejects a task created with a different reference video", async () => {
    vi.stubEnv("NODE_ENV", "development");
    vi.stubEnv("AVATAR_LOCAL_TEST_MODE", "true");
    vi.stubEnv("AVATAR_EVALUATION_LOOPBACK_BOUND", "true");
    dependencies.findAvatar.mockResolvedValue({ avatar_id: "avatar-123", deleted_at: null, actions: [{ avatar_action_id: "base", deleted_at: null, video_url: "/base.mp4" }] });
    dependencies.source.mockResolvedValue(Buffer.from("current source"));
    dependencies.trusted.mockReturnValue({ visualIdentityId: "avatar-123", model: "MiniMax-H3", referenceVideoSha256: "other" });
    expect((await POST(request(), context)).status).toBe(409);
    expect(dependencies.download).not.toHaveBeenCalled();
    expect(dependencies.attach).not.toHaveBeenCalled();
  });
});

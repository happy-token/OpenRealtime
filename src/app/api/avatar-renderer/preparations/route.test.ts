import { afterEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_AVATAR_DISPLAY_CONFIG } from "@/components/digital-human/types";

const processControl = vi.hoisted(() => ({ ensure: vi.fn() }));
const avatarCatalog = vi.hoisted(() => ({
  findOwnedAvatar: vi.fn(),
  updateOwnedAvatarAction: vi.fn(),
}));
vi.mock("@/lib/livetalking-process", () => ({
  ensureLiveTalkingProcess: processControl.ensure,
}));
vi.mock("@/lib/avatar-catalog-repository", () => ({
  findOwnedAvatar: avatarCatalog.findOwnedAvatar,
  updateOwnedAvatarAction: avatarCatalog.updateOwnedAvatarAction,
}));

import { GET, POST } from "./route";
import { resolveAvatarRendererBinding } from "@/lib/avatar-renderer-preparation";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  avatarCatalog.findOwnedAvatar.mockReset();
  avatarCatalog.updateOwnedAvatarAction.mockReset();
});

function enableLocalPreview() {
  vi.stubEnv("NODE_ENV", "development");
  vi.stubEnv("AVATAR_EVALUATION_PREVIEW_ENABLED", "true");
  vi.stubEnv("AVATAR_EVALUATION_LOCAL_PREVIEW_ENABLED", "true");
  vi.stubEnv("AVATAR_EVALUATION_LOOPBACK_BOUND", "true");
}

describe("avatar renderer preparation route", () => {
  it("makes a pending owned action available when its renderer asset is already ready", async () => {
    enableLocalPreview();
    vi.stubEnv("OPENREALTIME_AVATAR_RENDERER_MODE", "external");
    vi.stubEnv("OPENREALTIME_AVATAR_RENDERER_URL", "http://renderer.internal:8010");
    const config = {
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      renderPath: "segmented" as const,
      segmentedAvatarId: "avatar-123",
      segmentedDisplayName: "Lin",
      segmentedAvatarActionId: "action-ready",
      segmentedLipSyncId: "wav2lip256",
    };
    avatarCatalog.findOwnedAvatar.mockResolvedValue({
      avatar_id: "avatar-123",
      display_name: "Lin",
      source_image_url: "/api/avatars/avatar-123/image",
      created_at: "2026-08-31T00:00:00Z",
      updated_at: "2026-08-31T00:00:00Z",
      deleted_at: null,
      realtime_binding: null,
      actions: [{
        avatar_action_id: "action-ready",
        display_name: "侧头微笑",
        video_url: "/api/avatar-assets/artifacts/action-ready",
        pending_model_count: 1,
        created_at: "2026-08-31T00:00:00Z",
        deleted_at: null,
      }],
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      code: 0,
      data: { state: "ready", avatar_id: resolveAvatarRendererBinding(config)?.rendererAssetId },
    }))));

    const response = await POST(new Request("http://127.0.0.1:3010/api/avatar-renderer/preparations", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        referer: "http://127.0.0.1:3010/",
        "sec-fetch-site": "same-origin",
      },
      body: JSON.stringify(config),
    }));

    expect(response.status).toBe(200);
    expect(avatarCatalog.updateOwnedAvatarAction).toHaveBeenCalledWith(
      "avatar-123",
      "action-ready",
      { pendingModelCount: 0 },
    );
  });

  it("rejects a persisted action that was trashed when the Avatar image changed", async () => {
    enableLocalPreview();
    vi.stubEnv("OPENREALTIME_AVATAR_RENDERER_MODE", "external");
    vi.stubEnv("OPENREALTIME_AVATAR_RENDERER_URL", "http://renderer.internal:8010");
    const config = {
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      renderPath: "segmented" as const,
      segmentedAvatarId: "avatar-123",
      segmentedDisplayName: "Lin",
      segmentedAvatarActionId: "action-old",
      segmentedLipSyncId: "wav2lip256",
    };
    const rendererAssetId = resolveAvatarRendererBinding(config)?.rendererAssetId;
    avatarCatalog.findOwnedAvatar.mockResolvedValue({
      avatar_id: "avatar-123",
      display_name: "Lin",
      source_image_url: "/api/avatars/avatar-123/image",
      created_at: "2026-08-28T00:00:00Z",
      updated_at: "2026-08-31T00:00:00Z",
      deleted_at: null,
      realtime_binding: null,
      actions: [{
        avatar_action_id: "action-old",
        display_name: "旧动作",
        video_url: "/old.mp4",
        pending_model_count: 0,
        created_at: "2026-08-28T00:00:00Z",
        deleted_at: "2026-08-31T00:00:00Z",
      }],
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      code: 0,
      data: { state: "ready", avatar_id: rendererAssetId },
    }))));

    const response = await POST(new Request("http://127.0.0.1:3010/api/avatar-renderer/preparations", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        referer: "http://127.0.0.1:3010/",
        "sec-fetch-site": "same-origin",
      },
      body: JSON.stringify(config),
    }));

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({
      error: "已选择动作已删除，请重新选择形象或动作",
    });
  });

  it("reports a prepared avatar without requiring a task id", async () => {
    enableLocalPreview();
    vi.stubEnv("OPENREALTIME_AVATAR_RENDERER_MODE", "external");
    vi.stubEnv("OPENREALTIME_AVATAR_RENDERER_URL", "http://renderer.internal:8010");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      code: 0,
      data: { state: "ready", avatar_id: "wav2lip256-shuchang-3823145b" },
    }))));

    const response = await GET(new Request(
      "http://127.0.0.1:3010/api/avatar-renderer/preparations?rendererAssetId=wav2lip256-shuchang-3823145b",
      {
        headers: {
          referer: "http://127.0.0.1:3010/avatar-video",
          "sec-fetch-site": "same-origin",
        },
      },
    ));

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({
      state: "ready",
      progress: 100,
      rendererAssetId: "wav2lip256-shuchang-3823145b",
    });
  });

  it("makes a pending owned action available when preparation polling reaches ready", async () => {
    enableLocalPreview();
    vi.stubEnv("OPENREALTIME_AVATAR_RENDERER_MODE", "external");
    vi.stubEnv("OPENREALTIME_AVATAR_RENDERER_URL", "http://renderer.internal:8010");
    const config = {
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      renderPath: "segmented" as const,
      segmentedAvatarId: "avatar-123",
      segmentedAvatarActionId: "action-ready",
      segmentedLipSyncId: "wav2lip256",
    };
    const rendererAssetId = resolveAvatarRendererBinding(config)?.rendererAssetId ?? "";
    avatarCatalog.findOwnedAvatar.mockResolvedValue({
      avatar_id: "avatar-123",
      display_name: "Lin",
      source_image_url: "/api/avatars/avatar-123/image",
      created_at: "2026-08-31T00:00:00Z",
      updated_at: "2026-08-31T00:00:00Z",
      deleted_at: null,
      realtime_binding: null,
      actions: [{
        avatar_action_id: "action-ready",
        display_name: "侧头微笑",
        video_url: "/api/avatar-assets/artifacts/action-ready",
        pending_model_count: 1,
        created_at: "2026-08-31T00:00:00Z",
        deleted_at: null,
      }],
    });
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        code: 0,
        data: { status: "completed", progress: 100 },
      })))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        code: 0,
        data: { state: "ready", avatar_id: rendererAssetId },
      }))));
    const query = new URLSearchParams({
      taskId: "task-123",
      rendererAssetId,
      avatarId: "avatar-123",
      avatarActionId: "action-ready",
    });

    const response = await GET(new Request(
      `http://127.0.0.1:3010/api/avatar-renderer/preparations?${query}`,
      {
        headers: {
          referer: "http://127.0.0.1:3010/",
          "sec-fetch-site": "same-origin",
        },
      },
    ));

    expect(response.status).toBe(200);
    expect(avatarCatalog.updateOwnedAvatarAction).toHaveBeenCalledWith(
      "avatar-123",
      "action-ready",
      { pendingModelCount: 0 },
    );
  });

  it("rejects an uploaded static identity with an unsupported media type", async () => {
    enableLocalPreview();
    const form = new FormData();
    form.set("config", JSON.stringify({
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      renderPath: "segmented",
      segmentedAvatarId: "custom-12345678-1234-4123-8123-123456789abc",
      segmentedAvatarActionId: "builtin:identity-static:custom-12345678-1234-4123-8123-123456789abc",
      segmentedLipSyncId: "wav2lip256",
    }));
    form.set("source_image", new File(["not an image"], "identity.txt", { type: "text/plain" }));

    const response = await POST(new Request("http://127.0.0.1:3010/api/avatar-renderer/preparations", {
      method: "POST",
      headers: {
        referer: "http://127.0.0.1:3010/avatar-video",
        "sec-fetch-site": "same-origin",
      },
      body: form,
    }));

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({
      error: "仅支持 JPEG、PNG 或 WebP 形象图片",
    });
  });

  it("prepares Wav2Lip 96 assets on the isolated compatibility renderer", async () => {
    enableLocalPreview();
    const rendererRequest = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ code: 0, data: { state: "idle" } })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ code: 0, data: { task_id: "task-96" } })));
    vi.stubGlobal("fetch", rendererRequest);

    const response = await POST(new Request("http://127.0.0.1:3010/api/avatar-renderer/preparations", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        referer: "http://127.0.0.1:3010/",
        "sec-fetch-site": "same-origin",
      },
      body: JSON.stringify({
        ...DEFAULT_AVATAR_DISPLAY_CONFIG,
        renderPath: "segmented",
        segmentedLipSyncId: "wav2lip96",
        segmentedAvatarActionId: "builtin:liveportrait-optimized",
      }),
    }));

    expect(response.status).toBe(202);
    expect(processControl.ensure).toHaveBeenCalledWith(expect.any(String), 8011, 96);
    expect(String(rendererRequest.mock.calls[1]?.[0])).toContain("http://127.0.0.1:8011/api/avatar/task");
    const body = rendererRequest.mock.calls[1]?.[1]?.body as FormData;
    expect(body.get("img_size")).toBe("96");
    expect(body.get("avatar_id")).toBe("shuchang");
  });

  it("does not trust an uploaded identity MIME type without a matching signature", async () => {
    enableLocalPreview();
    const form = new FormData();
    form.set("config", JSON.stringify({
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      renderPath: "segmented",
      segmentedAvatarId: "custom-12345678-1234-4123-8123-123456789abc",
      segmentedAvatarActionId: "builtin:identity-static:custom-12345678-1234-4123-8123-123456789abc",
      segmentedLipSyncId: "wav2lip256",
    }));
    form.set("source_image", new File(["not a jpeg"], "identity.jpg", { type: "image/jpeg" }));

    const response = await POST(new Request("http://127.0.0.1:3010/api/avatar-renderer/preparations", {
      method: "POST",
      headers: {
        referer: "http://127.0.0.1:3010/avatar-video",
        "sec-fetch-site": "same-origin",
      },
      body: form,
    }));

    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toEqual({
      error: "形象图片内容与文件格式不匹配",
    });
  });
});

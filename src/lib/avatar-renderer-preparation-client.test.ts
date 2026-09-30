import { describe, expect, it, vi } from "vitest";
import {
  prepareAvatarRendererAsset,
  readAvatarRendererPreparationState,
} from "./avatar-renderer-preparation-client";
import { DEFAULT_AVATAR_DISPLAY_CONFIG } from "@/components/digital-human/types";

describe("prepareAvatarRendererAsset", () => {
  it("reads the durable ready state for the resolved avatar binding", async () => {
    const request = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      state: "ready",
      progress: 100,
      rendererAssetId: "wav2lip256-shuchang-3823145b",
    })));
    const displayConfig = {
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      renderPath: "segmented" as const,
      segmentedAvatarId: "shuchang",
      segmentedAvatarActionId: "builtin:identity-static:shuchang",
      segmentedLipSyncId: "wav2lip256",
    };

    const state = await readAvatarRendererPreparationState(displayConfig, { request });

    expect(state).toMatchObject({ state: "ready", progress: 100 });
    expect(String(request.mock.calls[0]?.[0])).toContain(
      "rendererAssetId=wav2lip256-shuchang-3823145b",
    );
  });

  it("keeps the task identity across progress responses that omit taskId", async () => {
    const request = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        state: "preparing",
        progress: 0,
        taskId: "task-1",
        rendererAssetId: "avatar-1",
      }), { status: 202 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        state: "preparing",
        progress: 35,
        rendererAssetId: "avatar-1",
      })))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        state: "ready",
        progress: 100,
        rendererAssetId: "avatar-1",
      })));
    const onProgress = vi.fn();
    const displayConfig = {
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      renderPath: "segmented" as const,
    };

    const result = await prepareAvatarRendererAsset(displayConfig, {
      request,
      wait: async () => {},
      onProgress,
    });

    expect(result).toMatchObject({ state: "ready", rendererAssetId: "avatar-1" });
    expect(request).toHaveBeenCalledTimes(3);
    expect(String(request.mock.calls[1]?.[0])).toContain("taskId=task-1");
    expect(String(request.mock.calls[2]?.[0])).toContain("taskId=task-1");
    expect(String(request.mock.calls[2]?.[0])).toContain("avatarId=avatar-8657be31-306e-428d-a013-7521e710ab6a");
    expect(String(request.mock.calls[2]?.[0])).toContain("avatarActionId=338a867c-0661-4565-af6e-f0f2e0e9b3c7");
    expect(onProgress).toHaveBeenNthCalledWith(1, 35);
    expect(onProgress).toHaveBeenNthCalledWith(2, 100);
  });

  it("submits an identity source image with the preparation configuration", async () => {
    const request = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      state: "ready",
      progress: 100,
      rendererAssetId: "avatar-static",
    })));
    const sourceImage = new Blob([
      Uint8Array.from([137, 80, 78, 71, 13, 10, 26, 10]),
    ], { type: "image/png" });

    await prepareAvatarRendererAsset(DEFAULT_AVATAR_DISPLAY_CONFIG, {
      request,
      sourceImage,
    });

    const body = request.mock.calls[0]?.[1]?.body;
    expect(body).toBeInstanceOf(FormData);
    expect((body as FormData).get("config")).toBe(JSON.stringify(DEFAULT_AVATAR_DISPLAY_CONFIG));
    const uploadedImage = (body as FormData).get("source_image");
    expect(uploadedImage).toBeInstanceOf(Blob);
    expect((uploadedImage as Blob).type).toBe("image/png");
    expect((uploadedImage as Blob).size).toBe(8);
  });

  it("reports an HTML route failure without exposing a JSON parser exception", async () => {
    const request = vi.fn().mockResolvedValue(new Response(
      "<pre>missing route module</pre>",
      { status: 404, headers: { "Content-Type": "text/html" } },
    ));

    await expect(prepareAvatarRendererAsset(DEFAULT_AVATAR_DISPLAY_CONFIG, { request }))
      .rejects.toThrow("口型资产准备请求失败（HTTP 404）");
  });
});

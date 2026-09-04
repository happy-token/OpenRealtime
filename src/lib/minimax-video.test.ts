import { beforeEach, describe, expect, it, vi } from "vitest";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {
  createMiniMaxImageToVideo,
  getMiniMaxGeneration,
  resetMiniMaxCachesForTest,
  uploadMiniMaxGenerationInput,
  validateMiniMaxVideoOptions,
} from "./minimax-video";

const environment = { MINIMAX_API_KEY: "test-key", MINIMAX_UPLOAD_CACHE_PATH: "" };
const imageDataUrl = `data:image/png;base64,${Buffer.from("image").toString("base64")}`;

describe("MiniMax H3 video provider", () => {
  beforeEach(resetMiniMaxCachesForTest);

  it("uploads the Avatar image once and uses it as both first and last frame", async () => {
    const fetcher = vi.fn<typeof fetch>(async (input) => String(input).endsWith("/v1/files/upload")
      ? Response.json({ file: { file_id: 123456 }, base_resp: { status_code: 0 } })
      : Response.json({ task_id: "437132157129088" }));
    const task = await createMiniMaxImageToVideo(environment, {
      imageDataUrl,
      prompt: "front-facing closed-mouth idle",
      model: "MiniMax-H3",
      ratio: "adaptive",
      resolution: "768P",
      duration: 6,
      imageRole: "first_and_last_frame",
    }, fetcher);

    expect(task).toMatchObject({ taskId: "437132157129088", state: "queueing", model: "MiniMax-H3" });
    expect(fetcher).toHaveBeenCalledTimes(2);
    const uploadForm = fetcher.mock.calls[0][1]?.body as FormData;
    expect(uploadForm.get("purpose")).toBe("video_generation_input");
    const createBody = JSON.parse(String(fetcher.mock.calls[1][1]?.body));
    expect(createBody).toMatchObject({
      model: "MiniMax-H3",
      resolution: "768P",
      duration: 6,
      ratio: "adaptive",
      content: [
        { type: "text", text: "front-facing closed-mouth idle" },
        { type: "image_url", image_url: { url: "mm_file://123456" }, role: "first_frame" },
        { type: "image_url", image_url: { url: "mm_file://123456" }, role: "last_frame" },
      ],
    });
  });

  it("maps the Avatar image to each supported H3 image role", async () => {
    for (const [imageRole, role] of [["first_frame", "first_frame"], ["last_frame", "last_frame"], ["reference_image", "reference_image"]] as const) {
      resetMiniMaxCachesForTest();
      const fetcher = vi.fn<typeof fetch>(async (input) => String(input).endsWith("/v1/files/upload")
        ? Response.json({ file: { file_id: imageRole }, base_resp: { status_code: 0 } })
        : Response.json({ task_id: `task_${imageRole}` }));
      await createMiniMaxImageToVideo(environment, {
        imageDataUrl,
        prompt: "front-facing idle",
        model: "MiniMax-H3",
        ratio: imageRole === "reference_image" ? "9:16" : "adaptive",
        resolution: "768P",
        duration: 6,
        imageRole,
      }, fetcher);

      const createBody = JSON.parse(String(fetcher.mock.calls[1][1]?.body));
      expect(createBody.content.slice(1)).toEqual([
        { type: "image_url", image_url: { url: `mm_file://${imageRole}` }, role },
      ]);
    }
  });

  it("accepts a fixed desired ratio for first/last-frame input prepared by the server", () => {
    expect(() => validateMiniMaxVideoOptions({
      model: "MiniMax-H3",
      ratio: "16:9",
      resolution: "768P",
      duration: 6,
      imageRole: "first_frame",
    })).not.toThrow();
  });

  it("deduplicates renamed and concurrent uploads by account, MIME type, and content hash", async () => {
    const fetcher = vi.fn<typeof fetch>(async () => Response.json({
      file: { file_id: "deduplicated-video" }, base_resp: { status_code: 0 },
    }));
    const bytes = Uint8Array.from([1, 2, 3, 4]);
    const [first, second] = await Promise.all([
      uploadMiniMaxGenerationInput(environment, { bytes, mediaType: "video/mp4", filename: "a.mp4" }, fetcher),
      uploadMiniMaxGenerationInput(environment, { bytes, mediaType: "video/mp4", filename: "renamed.mp4" }, fetcher),
    ]);
    const third = await uploadMiniMaxGenerationInput(environment, { bytes, mediaType: "video/mp4", filename: "again.mp4" }, fetcher);

    expect(fetcher).toHaveBeenCalledTimes(1);
    expect([first.reused, second.reused, third.reused]).toEqual([false, true, true]);
    expect(new Set([first.uri, second.uri, third.uri])).toEqual(new Set(["mm_file://deduplicated-video"]));
  });

  it("restores the paid-upload deduplication index after a service restart", async () => {
    const directory = await mkdtemp(path.join(os.tmpdir(), "openrealtime-minimax-cache-"));
    const persistentEnvironment = {
      MINIMAX_API_KEY: "persistent-test-key",
      MINIMAX_UPLOAD_CACHE_PATH: path.join(directory, "uploads.json"),
    };
    const firstFetcher = vi.fn<typeof fetch>(async () => Response.json({
      file: { file_id: "persisted-video" }, base_resp: { status_code: 0 },
    }));
    try {
      await uploadMiniMaxGenerationInput(persistentEnvironment, {
        bytes: Uint8Array.from([4, 3, 2, 1]), mediaType: "video/mp4", filename: "first.mp4",
      }, firstFetcher);
      resetMiniMaxCachesForTest();
      const secondFetcher = vi.fn<typeof fetch>();
      const restored = await uploadMiniMaxGenerationInput(persistentEnvironment, {
        bytes: Uint8Array.from([4, 3, 2, 1]), mediaType: "video/mp4", filename: "renamed.mp4",
      }, secondFetcher);

      expect(restored).toMatchObject({ uri: "mm_file://persisted-video", reused: true });
      expect(secondFetcher).not.toHaveBeenCalled();
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  });

  it("keeps first/last-frame generation mutually exclusive with multimodal references", async () => {
    await expect(createMiniMaxImageToVideo(environment, {
      imageDataUrl,
      prompt: "idle",
      model: "MiniMax-H3",
      ratio: "adaptive",
      resolution: "768P",
      duration: 6,
      imageRole: "first_and_last_frame",
      referenceVideo: { bytes: Uint8Array.from([1]), mediaType: "video/mp4", filename: "motion.mp4" },
    })).rejects.toMatchObject({ status: 400 });
  });

  it("uses reference_image with reference_video and runs Context IR before H3 generation", async () => {
    let uploadCount = 0;
    const fetcher = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/v1/files/upload")) {
        uploadCount += 1;
        return Response.json({ file: { file_id: uploadCount === 1 ? "avatar" : "motion" }, base_resp: { status_code: 0 } });
      }
      if (url.endsWith("/v2/h3_context_ir")) return Response.json({ task_id: "context_123456" });
      if (url.endsWith("/v2/query/video_generation/context_123456")) {
        return Response.json({ task: { id: "context_123456", status: "succeeded", content: { prompt: "enhanced prompt" } } });
      }
      if (url.endsWith("/v2/video_generation")) {
        expect(JSON.parse(String(init?.body))).toMatchObject({
          model: "MiniMax-H3",
          content: [
            { type: "text", text: "enhanced prompt" },
            { type: "image_url", role: "reference_image" },
            { type: "video_url", role: "reference_video" },
          ],
        });
        return Response.json({ task_id: "generation_123456" });
      }
      return Response.json({ task: { id: "generation_123456", status: "succeeded", content: { url: "https://cdn.example.com/context.mp4" } } });
    });
    const task = await createMiniMaxImageToVideo(environment, {
      imageDataUrl,
      prompt: "follow the reference motion",
      model: "MiniMax-H3-Context-IR",
      ratio: "9:16",
      resolution: "2K",
      duration: 8,
      imageRole: "reference_image",
      referenceVideo: { bytes: Uint8Array.from([9, 8, 7]), mediaType: "video/mp4", filename: "motion.mp4" },
    }, fetcher);
    expect(task.taskId).toBe("context_123456");
    await expect(getMiniMaxGeneration(environment, task.taskId, "MiniMax-H3-Context-IR", fetcher)).resolves.toMatchObject({ state: "queueing" });
    await expect(getMiniMaxGeneration(environment, task.taskId, "MiniMax-H3-Context-IR", fetcher)).resolves.toEqual({
      taskId: "context_123456", state: "success", videoUrl: "https://cdn.example.com/context.mp4",
    });
  });

  it("maps a completed H3 URL", async () => {
    const fetcher = vi.fn<typeof fetch>(async () => Response.json({
      task: { id: "437132157129088", status: "succeeded", content: { url: "https://video-product.cdn.minimax.io/output.mp4" } },
    }));
    await expect(getMiniMaxGeneration(environment, "437132157129088", "MiniMax-H3", fetcher)).resolves.toEqual({
      taskId: "437132157129088", state: "success", videoUrl: "https://video-product.cdn.minimax.io/output.mp4",
    });
  });

  it("rejects missing credentials before uploading", async () => {
    await expect(createMiniMaxImageToVideo({}, {
      imageDataUrl, prompt: "idle", model: "MiniMax-H3", ratio: "adaptive",
      resolution: "768P", duration: 6, imageRole: "first_and_last_frame",
    })).rejects.toMatchObject({ status: 503 });
  });
});

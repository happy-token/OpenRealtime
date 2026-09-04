import { describe, expect, it, vi } from "vitest";
import { createLtxImageToVideo, getLtxGeneration } from "./ltx-video";

const environment = { LTX_API_KEY: "test-key" };
const imageDataUrl = `data:image/png;base64,${Buffer.from("image").toString("base64")}`;

describe("LTX video provider", () => {
  it("submits the reviewed Avatar action defaults", async () => {
    const fetcher = vi.fn<typeof fetch>(async () => Response.json({
      id: "task_123456",
      created_at: "2026-08-31T10:00:00Z",
    }, { status: 202 }));
    const task = await createLtxImageToVideo(environment, {
      imageDataUrl,
      prompt: "front-facing closed-mouth idle",
      model: "ltx-2-3-fast",
    }, fetcher);
    expect(task).toMatchObject({ taskId: "task_123456", state: "queueing", model: "ltx-2-3-fast" });
    const [, init] = fetcher.mock.calls[0];
    expect(JSON.parse(String(init?.body))).toMatchObject({
      model: "ltx-2-3-fast",
      duration: 6,
      resolution: "720x1280",
      fps: 25,
      generate_audio: false,
      camera_motion: "static",
      image_uri: imageDataUrl,
      last_frame_uri: imageDataUrl,
    });
  });

  it("maps async terminal states and result URLs", async () => {
    const fetcher = vi.fn<typeof fetch>(async () => Response.json({
      id: "task_123456",
      status: "completed",
      result: { video_url: "https://media.ltx.test/result.mp4" },
    }));
    await expect(getLtxGeneration(environment, "task_123456", fetcher)).resolves.toEqual({
      taskId: "task_123456",
      state: "success",
      videoUrl: "https://media.ltx.test/result.mp4",
    });
  });

  it("rejects missing credentials before an external request", async () => {
    await expect(createLtxImageToVideo({}, {
      imageDataUrl,
      prompt: "idle",
      model: "ltx-2-3-fast",
    })).rejects.toMatchObject({ status: 503 });
  });
});

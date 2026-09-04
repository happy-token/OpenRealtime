import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

const worker = vi.hoisted(() => ({ getTask: vi.fn(), retain: vi.fn() }));

vi.mock("@/lib/liveportrait-worker", () => ({
  getLivePortraitTask: worker.getTask,
  retainLivePortraitTaskArtifact: worker.retain,
}));

import { GET } from "./route";

const taskId = "11111111-1111-4111-8111-111111111111";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

function enableLocalTestMode() {
  vi.stubEnv("NODE_ENV", "development");
  vi.stubEnv("AVATAR_LOCAL_TEST_MODE", "true");
  vi.stubEnv("AVATAR_EVALUATION_LOOPBACK_BOUND", "true");
}

function request(id = taskId) {
  return new NextRequest(`http://127.0.0.1:3010/api/liveportrait/${id}`, {
    headers: {
      host: "127.0.0.1:3010",
      origin: "http://127.0.0.1:3010",
      "sec-fetch-site": "same-origin",
    },
  });
}

function context(id = taskId) {
  return { params: Promise.resolve({ taskId: id }) };
}

describe("LivePortrait task route", () => {
  it("requires a trusted local or administrator request", async () => {
    expect((await GET(request(), context())).status).toBe(403);
  });

  it("rejects malformed and unknown task IDs", async () => {
    enableLocalTestMode();
    expect((await GET(request("bad"), context("bad"))).status).toBe(400);
    expect((await GET(request(), context())).status).toBe(404);
  });

  it("returns terminal task metadata without exposing the filesystem path", async () => {
    enableLocalTestMode();
    worker.getTask.mockReturnValue({
      id: taskId,
      state: "success",
      driverId: "breathing",
      sourceName: "portrait.jpg",
      createdAt: "2026-08-24T00:00:00.000Z",
      updatedAt: "2026-08-24T00:01:00.000Z",
      renderSeconds: 60.8,
      device: "mps",
      resultPath: "/private/tmp/secret/result.mp4",
    });
    const response = await GET(request(), context());
    expect(response.status).toBe(200);
    const payload = await response.json();
    expect(payload).toMatchObject({
      task_id: taskId,
      state: "success",
      result_url: `/api/liveportrait/${taskId}?artifact=1`,
      render_seconds: 60.8,
      device: "mps",
    });
    expect(JSON.stringify(payload)).not.toContain("/private/tmp");
  });

  it("releases the artifact lease when rejecting an invalid byte range", async () => {
    enableLocalTestMode();
    const release = vi.fn();
    worker.retain.mockReturnValue(release);
    worker.getTask.mockReturnValue({
      id: taskId,
      state: "success",
      driverId: "breathing",
      sourceName: "portrait.jpg",
      createdAt: "2026-08-24T00:00:00.000Z",
      updatedAt: "2026-08-24T00:01:00.000Z",
      resultPath: path.join(process.cwd(), "package.json"),
    });
    const artifactRequest = new NextRequest(`http://127.0.0.1:3010/api/liveportrait/${taskId}?artifact=1`, {
      headers: {
        host: "127.0.0.1:3010",
        origin: "http://127.0.0.1:3010",
        range: "bytes=999999999-1000000000",
        "sec-fetch-site": "same-origin",
      },
    });
    const response = await GET(artifactRequest, context());
    expect(response.status).toBe(416);
    expect(release).toHaveBeenCalledOnce();
  });
});

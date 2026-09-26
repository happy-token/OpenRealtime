import { describe, expect, it, vi } from "vitest";
import { runLipForcingServiceJob } from "./lipforcing-service-client";

describe("Lip Forcing service client", () => {
  it("submits the selected inputs, polls the GPU API and downloads the result", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(Response.json({ id: "lipforcing-job-1", state: "queued" }, { status: 202 }))
      .mockResolvedValueOnce(Response.json({ id: "lipforcing-job-1", state: "processing" }))
      .mockResolvedValueOnce(Response.json({ id: "lipforcing-job-1", state: "success" }))
      .mockResolvedValueOnce(new Response(new Uint8Array([1, 2, 3]), { headers: { "Content-Type": "video/mp4" } }));

    const output = await runLipForcingServiceJob({
      baseUrl: "http://127.0.0.1:18190/",
      token: "secret",
      jobId: "lipforcing-job-1",
      sourceVideo: Buffer.from("video"),
      referenceAudio: Buffer.from("audio"),
      fetcher,
      pollIntervalMs: 0,
    });

    expect(output).toEqual(Buffer.from([1, 2, 3]));
    expect(fetcher).toHaveBeenNthCalledWith(1, "http://127.0.0.1:18190/v1/jobs", expect.objectContaining({
      method: "POST",
      headers: { Authorization: "Bearer secret", "X-Job-Id": "lipforcing-job-1" },
    }));
    expect(fetcher).toHaveBeenNthCalledWith(4, "http://127.0.0.1:18190/v1/jobs/lipforcing-job-1/result", expect.objectContaining({
      headers: { Authorization: "Bearer secret" },
    }));
  });

  it("surfaces a failed GPU job without attempting a result download", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(Response.json({ id: "job-2", state: "queued" }, { status: 202 }))
      .mockResolvedValueOnce(Response.json({ id: "job-2", state: "failed", error: "inference failed" }));

    await expect(runLipForcingServiceJob({
      baseUrl: "http://127.0.0.1:18190",
      jobId: "job-2",
      sourceVideo: Buffer.from("video"),
      referenceAudio: Buffer.from("audio"),
      fetcher,
      pollIntervalMs: 0,
    })).rejects.toThrow("inference failed");
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("recovers from a temporary connection failure while polling an existing GPU job", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(Response.json({ id: "job-3", state: "processing" }, { status: 202 }))
      .mockRejectedValueOnce(new TypeError("fetch failed"))
      .mockResolvedValueOnce(Response.json({ id: "job-3", state: "success" }))
      .mockResolvedValueOnce(new Response(new Uint8Array([4, 5, 6])));

    const output = await runLipForcingServiceJob({
      baseUrl: "http://127.0.0.1:18190",
      jobId: "job-3",
      sourceVideo: Buffer.from("video"),
      referenceAudio: Buffer.from("audio"),
      fetcher,
      pollIntervalMs: 0,
      retryDelayMs: 0,
    });

    expect(output).toEqual(Buffer.from([4, 5, 6]));
    expect(fetcher).toHaveBeenCalledTimes(4);
  });
});

import { describe, expect, it, vi } from "vitest";
import { pollRecoverableGenerationTask } from "./generation-task-poll";

describe("generation task polling", () => {
  it("keeps a paid task recoverable when MiniMax is temporarily unreachable", async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json(
      { error: "暂时无法连接 MiniMax" },
      { status: 503 },
    ));

    await expect(pollRecoverableGenerationTask("/api/task-1", fetcher)).resolves.toEqual({
      kind: "retry",
      message: "暂时无法连接 MiniMax",
    });
  });

  it("retries a network failure instead of marking the provider task failed", async () => {
    const fetcher = vi.fn().mockRejectedValue(new TypeError("fetch failed"));

    await expect(pollRecoverableGenerationTask("/api/task-1", fetcher)).resolves.toEqual({
      kind: "retry",
      message: "视频生成状态暂时无法读取",
    });
  });

  it("keeps permanent task lookup failures terminal", async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json(
      { error: "视频生成任务不存在、已失效或服务已重启" },
      { status: 404 },
    ));

    await expect(pollRecoverableGenerationTask("/api/task-1", fetcher)).resolves.toEqual({
      kind: "failed",
      message: "视频生成任务不存在、已失效或服务已重启",
    });
  });
});

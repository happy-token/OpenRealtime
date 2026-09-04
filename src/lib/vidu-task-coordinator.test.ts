import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createOrReuseLocalViduTask,
  getTrustedLocalViduTask,
  releaseLocalViduTask,
  resetLocalViduTaskCoordinatorForTest,
} from "./vidu-task-coordinator";
import type { ViduGenerationTask } from "./vidu-video";

const task: ViduGenerationTask = {
  taskId: "task_123456",
  state: "created",
  model: "viduq3-pro-fast",
  offPeak: true,
};
const provenance = { visualIdentityId: "shuchang", sourceSha256: "a".repeat(64) };

afterEach(resetLocalViduTaskCoordinatorForTest);

describe("local Vidu task coordinator", () => {
  it("coalesces concurrent paid submissions", async () => {
    let resolveTask!: (value: ViduGenerationTask) => void;
    const create = vi.fn(() => new Promise<ViduGenerationTask>((resolve) => { resolveTask = resolve; }));
    const first = createOrReuseLocalViduTask(provenance, create);
    const second = createOrReuseLocalViduTask(provenance, create);
    resolveTask(task);
    await expect(first).resolves.toEqual({ task, reused: false });
    await expect(second).resolves.toEqual({ task, reused: true });
    expect(create).toHaveBeenCalledTimes(1);
  });

  it("keeps the lock until the matching provider task is terminal", async () => {
    const firstCreate = vi.fn(async () => task);
    await createOrReuseLocalViduTask(provenance, firstCreate);
    await expect(createOrReuseLocalViduTask(provenance, firstCreate)).resolves.toEqual({ task, reused: true });
    releaseLocalViduTask("another_task");
    await createOrReuseLocalViduTask(provenance, firstCreate);
    expect(firstCreate).toHaveBeenCalledTimes(1);
    releaseLocalViduTask(task.taskId);
    await createOrReuseLocalViduTask(provenance, firstCreate);
    expect(firstCreate).toHaveBeenCalledTimes(2);
  });

  it("retains trusted task provenance after releasing the paid-task lock", async () => {
    await createOrReuseLocalViduTask(provenance, async () => task);
    releaseLocalViduTask(task.taskId);
    expect(getTrustedLocalViduTask(task.taskId)).toMatchObject(provenance);
  });

  it("rejects reuse across visual identities or source images", async () => {
    await createOrReuseLocalViduTask(provenance, async () => task);
    await expect(createOrReuseLocalViduTask(
      { ...provenance, visualIdentityId: "custom-11111111-1111-4111-8111-111111111111" },
      async () => task,
    )).rejects.toThrow("另一数字人身份");
  });
});

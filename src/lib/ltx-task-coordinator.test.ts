import { afterEach, describe, expect, it } from "vitest";
import {
  createOrReuseLocalLtxTask,
  getTrustedLocalLtxTask,
  releaseLocalLtxTask,
  resetLocalLtxTaskCoordinatorForTest,
} from "./ltx-task-coordinator";

afterEach(resetLocalLtxTaskCoordinatorForTest);

const provenance = {
  visualIdentityId: "avatar-123",
  sourceSha256: "a".repeat(64),
  prompt: "idle",
  model: "ltx-2-3-fast" as const,
};

describe("LTX task coordinator", () => {
  it("reuses only an identical active request and retains trusted provenance", async () => {
    let creates = 0;
    const create = async () => {
      creates += 1;
      return { taskId: "task_123456", state: "queueing" as const, model: provenance.model, createdAt: new Date().toISOString() };
    };
    await expect(createOrReuseLocalLtxTask(provenance, create)).resolves.toMatchObject({ reused: false });
    await expect(createOrReuseLocalLtxTask(provenance, create)).resolves.toMatchObject({ reused: true });
    expect(creates).toBe(1);
    expect(getTrustedLocalLtxTask("task_123456")).toMatchObject(provenance);
  });

  it("does not let an abandoned request block a different set of parameters", async () => {
    await createOrReuseLocalLtxTask(provenance, async () => ({
      taskId: "task_123456",
      state: "queueing",
      model: provenance.model,
      createdAt: new Date().toISOString(),
    }));
    await expect(createOrReuseLocalLtxTask(
      { ...provenance, prompt: "different" },
      async () => ({ taskId: "task_654321", state: "queueing", model: provenance.model, createdAt: new Date().toISOString() }),
    )).resolves.toMatchObject({ task: { taskId: "task_654321" }, reused: false });
    releaseLocalLtxTask("task_123456");
  });

  it("allows an identical request to regenerate after its prior task reaches a terminal state", async () => {
    await createOrReuseLocalLtxTask(provenance, async () => ({
      taskId: "task_123456",
      state: "queueing",
      model: provenance.model,
      createdAt: new Date().toISOString(),
    }));
    releaseLocalLtxTask("task_123456");
    await expect(createOrReuseLocalLtxTask(provenance, async () => ({
      taskId: "task_654321",
      state: "queueing",
      model: provenance.model,
      createdAt: new Date().toISOString(),
    }))).resolves.toMatchObject({ task: { taskId: "task_654321" }, reused: false });
  });
});

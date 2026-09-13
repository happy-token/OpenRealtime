import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  createOrReuseLocalLtxTask,
  getLocalLtxSubmissionByRequestId,
  getTrustedLocalLtxTask,
  LtxTaskSubmissionPendingError,
  releaseLocalLtxTask,
  resetLocalLtxTaskCoordinatorForTest,
} from "./ltx-task-coordinator";

let taskRoot = "";

beforeEach(async () => {
  taskRoot = await mkdtemp(path.join(os.tmpdir(), "openrealtime-ltx-"));
  vi.stubEnv("OPENREALTIME_GENERATION_TASKS_PATH", path.join(taskRoot, "tasks.json"));
});

afterEach(async () => {
  resetLocalLtxTaskCoordinatorForTest();
  vi.unstubAllEnvs();
  await rm(taskRoot, { recursive: true, force: true });
});

const provenance = {
  visualIdentityId: "avatar-123",
  sourceSha256: "a".repeat(64),
  prompt: "idle",
  model: "ltx-2-3-fast" as const,
};

function task(taskId: string) {
  return { taskId, state: "queueing" as const, model: provenance.model, createdAt: new Date().toISOString() };
}

describe("LTX task coordinator", () => {
  it("reuses an identical active request and retains trusted provenance", async () => {
    let creates = 0;
    const create = async () => {
      creates += 1;
      return task("task_123456");
    };
    await expect(createOrReuseLocalLtxTask(provenance, create, { requestId: "request-1" })).resolves.toMatchObject({ reused: false });
    await expect(createOrReuseLocalLtxTask(provenance, create, { requestId: "request-2" })).resolves.toMatchObject({ reused: true });
    expect(creates).toBe(1);
    expect(getTrustedLocalLtxTask("task_123456")).toMatchObject(provenance);
    expect(getLocalLtxSubmissionByRequestId("request-2")).toMatchObject({ state: "active", task: { taskId: "task_123456" } });
  });

  it("restores trusted provider task metadata after process memory is cleared", async () => {
    await createOrReuseLocalLtxTask(provenance, async () => task("task_persisted"), { requestId: "request-persisted" });
    resetLocalLtxTaskCoordinatorForTest();
    expect(getTrustedLocalLtxTask("task_persisted")).toMatchObject({
      model: "ltx-2-3-fast",
      task: { taskId: "task_persisted" },
    });
  });

  it("fences an uncertain paid submission instead of charging again", async () => {
    await expect(createOrReuseLocalLtxTask(
      provenance,
      async () => { throw new Error("connection closed after submit"); },
      { requestId: "request-uncertain" },
    )).rejects.toThrow("connection closed");
    const duplicate = vi.fn(async () => task("task_duplicate"));
    await expect(createOrReuseLocalLtxTask(
      provenance,
      duplicate,
      { requestId: "request-after-refresh" },
    )).rejects.toBeInstanceOf(LtxTaskSubmissionPendingError);
    expect(duplicate).not.toHaveBeenCalled();
    expect(getLocalLtxSubmissionByRequestId("request-after-refresh")).toMatchObject({ state: "submission_unknown" });
  });

  it("does not let an active request block a different set of parameters", async () => {
    await createOrReuseLocalLtxTask(provenance, async () => task("task_123456"));
    await expect(createOrReuseLocalLtxTask(
      { ...provenance, prompt: "different" },
      async () => task("task_654321"),
    )).resolves.toMatchObject({ task: { taskId: "task_654321" }, reused: false });
    await releaseLocalLtxTask("task_123456", "failed");
  });


  it("reuses a completed successful result instead of buying the same generation again", async () => {
    await createOrReuseLocalLtxTask(provenance, async () => task("task_success"));
    await releaseLocalLtxTask("task_success", "success");
    const duplicate = vi.fn(async () => task("task_duplicate"));
    await expect(createOrReuseLocalLtxTask(provenance, duplicate)).resolves.toMatchObject({
      task: { taskId: "task_success" },
      reused: true,
    });
    expect(duplicate).not.toHaveBeenCalled();
  });

  it("allows an identical request to regenerate after its prior task reaches a terminal state", async () => {
    await createOrReuseLocalLtxTask(provenance, async () => task("task_123456"));
    await releaseLocalLtxTask("task_123456", "failed");
    await expect(createOrReuseLocalLtxTask(provenance, async () => task("task_654321")))
      .resolves.toMatchObject({ task: { taskId: "task_654321" }, reused: false });
  });
});

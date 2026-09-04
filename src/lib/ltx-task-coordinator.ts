import type { VideoGenerationModelId } from "./ltx-avatar-action";
import type { VideoGenerationTask } from "./video-generation-types";

const TRUSTED_TASK_TTL_MS = 6 * 60 * 60 * 1_000;

export type LtxTaskProvenance = {
  visualIdentityId: string;
  sourceSha256: string;
  prompt: string;
  model: VideoGenerationModelId;
  ratio?: string;
  resolution?: string;
  duration?: number;
  imageRole?: string;
  referenceVideoSha256?: string;
};

export type TrustedLtxTask = LtxTaskProvenance & {
  task: VideoGenerationTask;
  createdAt: string;
  terminal: boolean;
};

type CoordinatorStore = {
  pendingCreations: Map<string, Promise<VideoGenerationTask>>;
  tasks: Map<string, TrustedLtxTask>;
};

const globalCoordinator = globalThis as typeof globalThis & {
  __openrealtimeLtxTaskCoordinator?: CoordinatorStore;
};
const store: CoordinatorStore = globalCoordinator.__openrealtimeLtxTaskCoordinator ??= {
  pendingCreations: new Map(),
  tasks: new Map(),
};

export async function createOrReuseLocalLtxTask(
  provenance: LtxTaskProvenance,
  create: () => Promise<VideoGenerationTask>,
): Promise<{ task: VideoGenerationTask; reused: boolean }> {
  pruneExpiredTasks();
  const active = [...store.tasks.values()].find((record) => !record.terminal && sameProvenance(record, provenance));
  if (active) {
    return { task: active.task, reused: true };
  }
  const key = provenanceKey(provenance);
  const existingPending = store.pendingCreations.get(key);
  if (existingPending) {
    return { task: await existingPending, reused: true };
  }
  const pending = create();
  store.pendingCreations.set(key, pending);
  try {
    const task = await pending;
    store.tasks.set(task.taskId, {
      task,
      ...provenance,
      createdAt: new Date().toISOString(),
      terminal: false,
    });
    return { task, reused: false };
  } finally {
    if (store.pendingCreations.get(key) === pending) store.pendingCreations.delete(key);
  }
}

export function getTrustedLocalLtxTask(taskId: string) {
  const record = store.tasks.get(taskId);
  if (record && Date.now() - Date.parse(record.createdAt) >= TRUSTED_TASK_TTL_MS) {
    store.tasks.delete(taskId);
    return undefined;
  }
  return record;
}

export function releaseLocalLtxTask(taskId: string) {
  const record = store.tasks.get(taskId);
  if (record) record.terminal = true;
}

export function resetLocalLtxTaskCoordinatorForTest() {
  store.pendingCreations.clear();
  store.tasks.clear();
}

function sameProvenance(left: LtxTaskProvenance, right: LtxTaskProvenance) {
  return provenanceKey(left) === provenanceKey(right);
}

function provenanceKey(value: LtxTaskProvenance) {
  return JSON.stringify([
    value.visualIdentityId,
    value.sourceSha256,
    value.prompt,
    value.model,
    value.ratio ?? null,
    value.resolution ?? null,
    value.duration ?? null,
    value.imageRole ?? null,
    value.referenceVideoSha256 ?? null,
  ]);
}

function pruneExpiredTasks() {
  for (const [taskId, record] of store.tasks) {
    if (Date.now() - Date.parse(record.createdAt) >= TRUSTED_TASK_TTL_MS) {
      store.tasks.delete(taskId);
    }
  }
}

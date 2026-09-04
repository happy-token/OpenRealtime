import type { ViduGenerationTask } from "./vidu-video";

const TRUSTED_TASK_TTL_MS = 6 * 60 * 60 * 1_000;

export type ViduTaskProvenance = {
  visualIdentityId: string;
  sourceSha256: string;
};

export type TrustedViduTask = ViduTaskProvenance & {
  task: ViduGenerationTask;
  createdAt: string;
};

export class ViduTaskConflictError extends Error {
  constructor() {
    super("已有另一数字人身份的 Vidu 任务正在运行，请等待其结束");
    this.name = "ViduTaskConflictError";
  }
}

type CoordinatorStore = {
  activeTaskId?: string;
  pendingCreation?: { provenance: ViduTaskProvenance; promise: Promise<ViduGenerationTask> };
  tasks: Map<string, TrustedViduTask>;
};

const globalCoordinator = globalThis as typeof globalThis & {
  __openrealtimeViduTaskCoordinator?: CoordinatorStore;
};
const store: CoordinatorStore = globalCoordinator.__openrealtimeViduTaskCoordinator ??= {
  tasks: new Map(),
};

export async function createOrReuseLocalViduTask(
  provenance: ViduTaskProvenance,
  create: () => Promise<ViduGenerationTask>,
): Promise<{ task: ViduGenerationTask; reused: boolean }> {
  pruneExpiredTasks();
  const active = store.activeTaskId ? store.tasks.get(store.activeTaskId) : undefined;
  if (active) {
    if (!sameProvenance(active, provenance)) throw new ViduTaskConflictError();
    return { task: active.task, reused: true };
  }
  if (store.pendingCreation) {
    if (!sameProvenance(store.pendingCreation.provenance, provenance)) throw new ViduTaskConflictError();
    return { task: await store.pendingCreation.promise, reused: true };
  }

  const pending = { provenance, promise: create() };
  store.pendingCreation = pending;
  try {
    const task = await pending.promise;
    store.tasks.set(task.taskId, {
      task,
      ...provenance,
      createdAt: new Date().toISOString(),
    });
    store.activeTaskId = task.taskId;
    return { task, reused: false };
  } finally {
    if (store.pendingCreation === pending) store.pendingCreation = undefined;
  }
}

export function releaseLocalViduTask(taskId: string) {
  if (store.activeTaskId === taskId) store.activeTaskId = undefined;
}

export function getTrustedLocalViduTask(taskId: string): TrustedViduTask | undefined {
  const record = store.tasks.get(taskId);
  if (record && Date.now() - Date.parse(record.createdAt) >= TRUSTED_TASK_TTL_MS) {
    store.tasks.delete(taskId);
    if (store.activeTaskId === taskId) store.activeTaskId = undefined;
    return undefined;
  }
  return record;
}

export function resetLocalViduTaskCoordinatorForTest() {
  store.activeTaskId = undefined;
  store.pendingCreation = undefined;
  store.tasks.clear();
}

function sameProvenance(
  left: ViduTaskProvenance,
  right: ViduTaskProvenance,
) {
  return left.visualIdentityId === right.visualIdentityId
    && left.sourceSha256 === right.sourceSha256;
}

function pruneExpiredTasks() {
  for (const [taskId, record] of store.tasks) {
    if (Date.now() - Date.parse(record.createdAt) >= TRUSTED_TASK_TTL_MS) {
      store.tasks.delete(taskId);
      if (store.activeTaskId === taskId) store.activeTaskId = undefined;
    }
  }
}

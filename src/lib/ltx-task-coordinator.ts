import { createHash, randomUUID } from "node:crypto";
import { mkdir, readFile, rename, rm, stat, writeFile } from "node:fs/promises";
import { readFileSync } from "node:fs";
import path from "node:path";
import type { VideoGenerationModelId } from "./ltx-avatar-action";
import type { VideoGenerationTask } from "./video-generation-types";

const TRUSTED_TASK_TTL_MS = 7 * 24 * 60 * 60 * 1_000;
const LOCK_RETRY_MS = 25;
const LOCK_TIMEOUT_MS = 5_000;
const STALE_LOCK_MS = 30_000;

export type LtxTaskProvenance = {
  visualIdentityId: string;
  credentialFingerprint?: string;
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
  updatedAt: string;
  terminal: boolean;
  requestIds: string[];
};

export type LtxSubmissionRecord = LtxTaskProvenance & {
  id: string;
  requestIds: string[];
  state: "submitting" | "active" | "terminal" | "submission_unknown";
  task?: VideoGenerationTask;
  createdAt: string;
  updatedAt: string;
  error?: string;
  outcome?: "success" | "failed";
};

export class LtxTaskSubmissionPendingError extends Error {
  constructor(public readonly record: LtxSubmissionRecord) {
    super(record.state === "submission_unknown"
      ? "上次付费任务的提交结果无法确认。为避免重复扣费，系统不会自动重试，请先核对服务商任务记录。"
      : "付费任务正在提交，刷新页面后会自动恢复进度。");
    this.name = "LtxTaskSubmissionPendingError";
  }
}

type CoordinatorStore = {
  pendingCreations: Map<string, Promise<VideoGenerationTask>>;
  tasks: Map<string, TrustedLtxTask>;
};

type CoordinatorOptions = { requestId?: string; storagePath?: string };

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
  options: CoordinatorOptions = {},
): Promise<{ task: VideoGenerationTask; reused: boolean }> {
  const storagePath = options.storagePath ?? defaultStoragePath();
  const key = provenanceKey(provenance);
  const requestId = options.requestId;
  const inProcess = store.pendingCreations.get(key);
  if (inProcess) return { task: await inProcess, reused: true };

  const claim = await withLedgerLock(storagePath, async () => {
    const records = await readLedger(storagePath);
    pruneExpiredRecords(records);
    const byRequestId = requestId ? records.find(record => record.requestIds.includes(requestId)) : undefined;
    if (byRequestId && provenanceKey(byRequestId) !== key) throw new Error("生成请求 ID 已被其他参数使用");
    const existing = byRequestId || records.find((record) =>
      (record.state !== "terminal" || record.outcome === "success") && provenanceKey(record) === key);
    if (existing) {
      if (requestId && !existing.requestIds.includes(requestId)) existing.requestIds.push(requestId);
      existing.updatedAt = new Date().toISOString();
      await writeLedger(storagePath, records);
      return { record: existing, claimed: false };
    }
    const now = new Date().toISOString();
    const record: LtxSubmissionRecord = {
      id: randomUUID(),
      ...provenance,
      requestIds: requestId ? [requestId] : [],
      state: "submitting",
      createdAt: now,
      updatedAt: now,
    };
    records.push(record);
    await writeLedger(storagePath, records);
    return { record, claimed: true };
  });

  if (!claim.claimed) {
    if (claim.record.task) {
      rememberTrusted(claim.record);
      return { task: claim.record.task, reused: true };
    }
    throw new LtxTaskSubmissionPendingError(claim.record);
  }

  const pending = create();
  store.pendingCreations.set(key, pending);
  try {
    const task = await pending;
    const persisted = await updateRecord(storagePath, claim.record.id, (record) => ({
      ...record,
      state: "active",
      task,
      error: undefined,
      updatedAt: new Date().toISOString(),
    }));
    rememberTrusted(persisted);
    return { task, reused: false };
  } catch (error) {
    await updateRecord(storagePath, claim.record.id, (record) => ({
      ...record,
      state: "submission_unknown",
      error: error instanceof Error ? error.message : "任务提交结果未知",
      updatedAt: new Date().toISOString(),
    }));
    throw error;
  } finally {
    if (store.pendingCreations.get(key) === pending) store.pendingCreations.delete(key);
  }
}

export function getLocalLtxSubmissionByRequestId(requestId: string, storagePath = defaultStoragePath()) {
  return readLedgerSync(storagePath).find((record) => record.requestIds.includes(requestId));
}

export function getTrustedLocalLtxTask(taskId: string, storagePath = defaultStoragePath()) {
  const memoryRecord = store.tasks.get(taskId);
  if (memoryRecord && !isExpired(memoryRecord.updatedAt)) return memoryRecord;
  if (memoryRecord) store.tasks.delete(taskId);
  const record = readLedgerSync(storagePath).find((candidate) => candidate.task?.taskId === taskId);
  if (!record?.task || isExpired(record.updatedAt)) return undefined;
  rememberTrusted(record);
  return store.tasks.get(taskId);
}

export async function releaseLocalLtxTask(
  taskId: string,
  outcome?: "success" | "failed",
  storagePath = defaultStoragePath(),
) {
  const record = store.tasks.get(taskId);
  if (record) record.terminal = true;
  await withLedgerLock(storagePath, async () => {
    const records = await readLedger(storagePath);
    const index = records.findIndex((candidate) => candidate.task?.taskId === taskId);
    if (index < 0) return;
    records[index] = { ...records[index], state: "terminal", outcome, updatedAt: new Date().toISOString() };
    await writeLedger(storagePath, records);
  });
}

export function resetLocalLtxTaskCoordinatorForTest() {
  store.pendingCreations.clear();
  store.tasks.clear();
}

function rememberTrusted(record: LtxSubmissionRecord) {
  if (!record.task) return;
  store.tasks.set(record.task.taskId, {
    ...provenanceOf(record),
    task: record.task,
    createdAt: record.createdAt,
    updatedAt: record.updatedAt,
    terminal: record.state === "terminal",
    requestIds: record.requestIds,
  });
}

function provenanceOf(value: LtxTaskProvenance): LtxTaskProvenance {
  return {
    visualIdentityId: value.visualIdentityId,
    credentialFingerprint: value.credentialFingerprint,
    sourceSha256: value.sourceSha256,
    prompt: value.prompt,
    model: value.model,
    ratio: value.ratio,
    resolution: value.resolution,
    duration: value.duration,
    imageRole: value.imageRole,
    referenceVideoSha256: value.referenceVideoSha256,
  };
}

function provenanceKey(value: LtxTaskProvenance) {
  return createHash("sha256").update(JSON.stringify([
    value.visualIdentityId,
    value.credentialFingerprint ?? null,
    value.sourceSha256,
    value.prompt,
    value.model,
    value.ratio ?? null,
    value.resolution ?? null,
    value.duration ?? null,
    value.imageRole ?? null,
    value.referenceVideoSha256 ?? null,
  ])).digest("hex");
}

function defaultStoragePath() {
  return process.env.OPENREALTIME_GENERATION_TASKS_PATH
    ?? path.join(process.cwd(), ".openrealtime", "generation-jobs", "video-generation.json");
}

async function updateRecord(storagePath: string, id: string, update: (record: LtxSubmissionRecord) => LtxSubmissionRecord) {
  return await withLedgerLock(storagePath, async () => {
    const records = await readLedger(storagePath);
    const index = records.findIndex((record) => record.id === id);
    if (index < 0) throw new Error("生成任务持久化记录已丢失");
    records[index] = update(records[index]);
    await writeLedger(storagePath, records);
    return records[index];
  });
}

async function withLedgerLock<T>(storagePath: string, operation: () => Promise<T>): Promise<T> {
  const lockPath = `${storagePath}.lock`;
  await mkdir(path.dirname(storagePath), { recursive: true, mode: 0o700 });
  const deadline = Date.now() + LOCK_TIMEOUT_MS;
  while (true) {
    try {
      await mkdir(lockPath);
      break;
    } catch (error) {
      if (!isAlreadyExists(error) || Date.now() >= deadline) throw error;
      const lockStat = await stat(lockPath).catch(() => undefined);
      if (lockStat && Date.now() - lockStat.mtimeMs > STALE_LOCK_MS) {
        await rm(lockPath, { recursive: true, force: true });
        continue;
      }
      await new Promise((resolve) => setTimeout(resolve, LOCK_RETRY_MS));
    }
  }
  try {
    return await operation();
  } finally {
    await rm(lockPath, { recursive: true, force: true });
  }
}

async function readLedger(storagePath: string): Promise<LtxSubmissionRecord[]> {
  try {
    const parsed: unknown = JSON.parse(await readFile(storagePath, "utf8"));
    return Array.isArray(parsed) ? parsed.filter(isSubmissionRecord) : [];
  } catch (error) {
    if (isNotFound(error)) return [];
    throw error;
  }
}

function readLedgerSync(storagePath: string): LtxSubmissionRecord[] {
  try {
    const parsed: unknown = JSON.parse(readFileSync(storagePath, "utf8"));
    return Array.isArray(parsed) ? parsed.filter(isSubmissionRecord) : [];
  } catch (error) {
    if (isNotFound(error)) return [];
    throw error;
  }
}

async function writeLedger(storagePath: string, records: LtxSubmissionRecord[]) {
  const temporaryPath = `${storagePath}.${process.pid}.${randomUUID()}.tmp`;
  await writeFile(temporaryPath, JSON.stringify(records, null, 2), { mode: 0o600 });
  await rename(temporaryPath, storagePath);
}

function pruneExpiredRecords(records: LtxSubmissionRecord[]) {
  const retained = records.filter((record) => !isExpired(record.updatedAt));
  records.splice(0, records.length, ...retained);
}

function isExpired(timestamp: string) {
  return Date.now() - Date.parse(timestamp) >= TRUSTED_TASK_TTL_MS;
}

function isSubmissionRecord(value: unknown): value is LtxSubmissionRecord {
  if (!value || typeof value !== "object") return false;
  const record = value as Partial<LtxSubmissionRecord>;
  return typeof record.id === "string"
    && Array.isArray(record.requestIds)
    && typeof record.visualIdentityId === "string"
    && typeof record.sourceSha256 === "string"
    && typeof record.prompt === "string"
    && typeof record.model === "string"
    && typeof record.createdAt === "string"
    && typeof record.updatedAt === "string"
    && ["submitting", "active", "terminal", "submission_unknown"].includes(record.state ?? "");
}

function isNotFound(error: unknown) {
  return error instanceof Error && "code" in error && error.code === "ENOENT";
}

function isAlreadyExists(error: unknown) {
  return error instanceof Error && "code" in error && error.code === "EEXIST";
}

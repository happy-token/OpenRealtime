export type RecoverableGenerationProvider = "liveportrait" | "ltx" | "minimax";

export type RecoverableGenerationTask = {
  avatarId: string;
  purpose: "action" | "talking";
  requestId: string;
  provider: RecoverableGenerationProvider;
  taskId?: string;
  displayName?: string;
  sourceId?: string;
  sourceUrl?: string;
  startedAt: number;
};

const MAX_RECOVERY_AGE_MS = 7 * 24 * 60 * 60 * 1_000;
const PREFIX = "openrealtime:generation-task:";

export function generationTaskStorageKey(avatarId: string, purpose: RecoverableGenerationTask["purpose"]) {
  return `${PREFIX}${avatarId}:${purpose}`;
}

export function saveRecoverableGenerationTask(
  task: RecoverableGenerationTask,
  storage: Pick<Storage, "setItem"> = window.localStorage,
) {
  storage.setItem(generationTaskStorageKey(task.avatarId, task.purpose), JSON.stringify(task));
}

export function readRecoverableGenerationTask(
  avatarId: string,
  purpose: RecoverableGenerationTask["purpose"],
  storage: Pick<Storage, "getItem" | "removeItem"> = window.localStorage,
  now = Date.now(),
): RecoverableGenerationTask | undefined {
  const key = generationTaskStorageKey(avatarId, purpose);
  try {
    const parsed: unknown = JSON.parse(storage.getItem(key) ?? "null");
    if (!isRecoverableTask(parsed) || parsed.avatarId !== avatarId || parsed.purpose !== purpose || now - parsed.startedAt > MAX_RECOVERY_AGE_MS) {
      storage.removeItem(key);
      return undefined;
    }
    return parsed;
  } catch {
    storage.removeItem(key);
    return undefined;
  }
}

export function clearRecoverableGenerationTask(
  avatarId: string,
  purpose: RecoverableGenerationTask["purpose"],
  storage: Pick<Storage, "removeItem"> = window.localStorage,
) {
  storage.removeItem(generationTaskStorageKey(avatarId, purpose));
}

export function shouldRecoverGenerationSubmission({
  requestId,
  taskId,
  provider,
  taskState,
  submissionInFlight,
}: {
  requestId: string;
  taskId: string;
  provider: RecoverableGenerationProvider;
  taskState: string;
  submissionInFlight: boolean;
}) {
  return Boolean(requestId)
    && !taskId
    && (provider === "ltx" || provider === "minimax")
    && taskState === "queueing"
    && !submissionInFlight;
}

function isRecoverableTask(value: unknown): value is RecoverableGenerationTask {
  if (!value || typeof value !== "object") return false;
  const task = value as Partial<RecoverableGenerationTask>;
  return typeof task.avatarId === "string"
    && ["action", "talking"].includes(task.purpose ?? "")
    && typeof task.requestId === "string"
    && ["liveportrait", "ltx", "minimax"].includes(task.provider ?? "")
    && (task.taskId === undefined || typeof task.taskId === "string")
    && (task.displayName === undefined || typeof task.displayName === "string")
    && (task.sourceId === undefined || typeof task.sourceId === "string")
    && (task.sourceUrl === undefined || typeof task.sourceUrl === "string")
    && typeof task.startedAt === "number"
    && Number.isFinite(task.startedAt);
}

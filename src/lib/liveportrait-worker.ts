import { createHash, randomUUID } from "node:crypto";
import { execFile, spawn, type ChildProcess } from "node:child_process";
import { chmod, lstat, mkdir, readFile, readdir, realpath, rm, stat, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { LIVEPORTRAIT_ACTIONS } from "./liveportrait-actions";
import type { LivePortraitMotionConfig } from "./liveportrait-motion-config";
import { modelServiceConnection, probeModelService, type ModelServiceConnection } from "./model-service-connections";
import { runInferenceServiceJob } from "./lipforcing-service-client";

const execFileAsync = promisify(execFile);
const MAX_LOG_CHARS = 8_000;
const SUCCESS_TASK_TTL_MS = 7 * 24 * 60 * 60 * 1_000;
const FAILED_TASK_TTL_MS = 15 * 60 * 1_000;
const TASK_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

export type LivePortraitTaskState = "queueing" | "processing" | "success" | "failed";
export type LivePortraitTask = {
  id: string;
  state: LivePortraitTaskState;
  createdAt: string;
  updatedAt: string;
  driverId: string;
  sourceName: string;
  visualIdentityId: string;
  sourceSha256: string;
  livePortraitConfig: LivePortraitMotionConfig;
  resultPath?: string;
  renderSeconds?: number;
  device?: string;
  error?: string;
};

export type LivePortraitRuntimeStatus = {
  ready: boolean;
  device: string;
  weightsBytes: number;
  issues: string[];
  templates: Array<{ id: string; available: boolean }>;
};

export type LivePortraitDrivingInspection = {
  eligible: boolean;
  reason?: string;
  durationSeconds: number;
  sampleCount: number;
  medianRatio: number;
  maximumRatio: number;
};

export type LivePortraitTaskInput = {
  sourceBytes: Uint8Array;
  sourceExtension: ".jpg" | ".png" | ".webp";
  sourceName: string;
  visualIdentityId: string;
  driverId: string;
  drivingBytes?: Uint8Array;
  drivingExtension?: ".mp4" | ".webm" | ".mov";
  livePortraitConfig: LivePortraitMotionConfig;
  projectRoot?: string;
  taskRoot?: string;
  wrapperPython?: string;
};

type WorkerStore = {
  tasks: Map<string, LivePortraitTask>;
  activeTaskId?: string;
  pendingCreation?: Promise<{ task: LivePortraitTask; reused: boolean }>;
  taskDirectories: Map<string, { root: string; taskDir: string }>;
  readerCounts: Map<string, number>;
  cleanupDue: Set<string>;
  cleanupTimers: Map<string, ReturnType<typeof setTimeout>>;
  orphanScanStarted?: boolean;
};

const globalWorker = globalThis as typeof globalThis & {
  __openrealtimeLivePortraitWorker?: WorkerStore;
};
const store: WorkerStore = globalWorker.__openrealtimeLivePortraitWorker ??= {
  tasks: new Map<string, LivePortraitTask>(),
  taskDirectories: new Map(),
  readerCounts: new Map(),
  cleanupDue: new Set(),
  cleanupTimers: new Map(),
};
store.taskDirectories ??= new Map();
store.readerCounts ??= new Map();
store.cleanupDue ??= new Set();
store.cleanupTimers ??= new Map();
if (!store.orphanScanStarted) {
  store.orphanScanStarted = true;
  void reconcileLivePortraitTaskRoot(defaultTaskRoot()).catch((error) => {
    console.error("Failed to inspect orphaned LivePortrait tasks", error);
  });
}

export function resolveLivePortraitTemplate(
  driverId: string,
  projectRoot = process.cwd(),
  runtimeRoot = process.env.LIVEPORTRAIT_RUNTIME_ROOT ?? path.join(projectRoot, "models/liveportrait"),
) {
  const action = LIVEPORTRAIT_ACTIONS.find((item) => item.id === driverId);
  if (!action) return null;
  const root = action.source.scope === "runtime" ? runtimeRoot : projectRoot;
  return path.join(root, action.source.relativePath);
}

export function buildLivePortraitRenderInvocation({
  sourcePath,
  drivingPath,
  outputDir,
  configPath,
  projectRoot = process.cwd(),
  runtimeRoot = process.env.LIVEPORTRAIT_RUNTIME_ROOT ?? path.join(projectRoot, "models/liveportrait"),
  wrapperPython = process.env.LIVEPORTRAIT_WRAPPER_PYTHON ?? "python3",
}: {
  sourcePath: string;
  drivingPath: string;
  outputDir: string;
  configPath?: string;
  projectRoot?: string;
  runtimeRoot?: string;
  wrapperPython?: string;
}) {
  return {
    command: wrapperPython,
    args: [
      path.join(projectRoot, "scripts/liveportrait_provider.py"),
      "render",
      sourcePath,
      drivingPath,
      outputDir,
      "--runtime-root",
      runtimeRoot,
      "--rights-confirmed",
      "--timeout-seconds",
      "900",
      ...(configPath ? ["--config-json", configPath] : []),
    ],
    cwd: projectRoot,
  };
}

export function buildLivePortraitDrivingInspectionInvocation({
  drivingPath,
  projectRoot = process.cwd(),
  runtimeRoot = process.env.LIVEPORTRAIT_RUNTIME_ROOT ?? path.join(projectRoot, "models/liveportrait"),
  wrapperPython = process.env.LIVEPORTRAIT_WRAPPER_PYTHON ?? "python3",
}: {
  drivingPath: string;
  projectRoot?: string;
  runtimeRoot?: string;
  wrapperPython?: string;
}) {
  return {
    command: wrapperPython,
    args: [
      path.join(projectRoot, "scripts/liveportrait_provider.py"),
      "inspect-driving",
      drivingPath,
      "--runtime-root",
      runtimeRoot,
    ],
    cwd: projectRoot,
  };
}

export async function inspectLivePortraitWorker(projectRoot = process.cwd()): Promise<LivePortraitRuntimeStatus> {
  const wrapperPython = process.env.LIVEPORTRAIT_WRAPPER_PYTHON ?? "python3";
  const runtimeRoot = process.env.LIVEPORTRAIT_RUNTIME_ROOT ?? path.join(projectRoot, "models/liveportrait");
  const templates = await Promise.all(LIVEPORTRAIT_ACTIONS.map(async ({ id }) => ({
    id,
    available: await isRegularFile(resolveLivePortraitTemplate(id, projectRoot, runtimeRoot)),
  })));
  const connection = await modelServiceConnection("liveportrait");
  if (connection.url) {
    const probe = await probeModelService("liveportrait", connection);
    return { ready: probe.ready, device: "remote", weightsBytes: 0, issues: probe.ready ? [] : [probe.message], templates };
  }
  try {
    const { stdout } = await execFileAsync(wrapperPython, [
      path.join(projectRoot, "scripts/liveportrait_provider.py"),
      "diagnose",
      "--runtime-root",
      runtimeRoot,
    ], { cwd: projectRoot, timeout: 20_000, maxBuffer: 128 * 1024 });
    const diagnostic = JSON.parse(stdout.trim()) as {
      ready?: unknown;
      device?: unknown;
      weights_bytes?: unknown;
      issues?: unknown;
    };
    return {
      ready: diagnostic.ready === true,
      device: typeof diagnostic.device === "string" ? diagnostic.device : "unknown",
      weightsBytes: typeof diagnostic.weights_bytes === "number" ? diagnostic.weights_bytes : 0,
      issues: Array.isArray(diagnostic.issues) ? diagnostic.issues.filter((issue): issue is string => typeof issue === "string") : [],
      templates,
    };
  } catch {
    return {
      ready: false,
      device: "unknown",
      weightsBytes: 0,
      issues: ["LivePortrait Runtime 诊断失败"],
      templates,
    };
  }
}

export async function inspectLivePortraitDrivingFile({
  drivingPath,
  projectRoot = process.cwd(),
  wrapperPython = process.env.LIVEPORTRAIT_WRAPPER_PYTHON ?? "python3",
}: {
  drivingPath: string;
  projectRoot?: string;
  wrapperPython?: string;
}) {
  const connection = await modelServiceConnection("liveportrait");
  if (connection.url) {
    const form = new FormData();
    const extension = path.extname(drivingPath).toLowerCase();
    const type = extension === ".webm" ? "video/webm" : extension === ".mov" ? "video/quicktime" : "video/mp4";
    form.set("driving_video", new Blob([new Uint8Array(await readFile(drivingPath))], { type }), `driving${extension}`);
    const response = await fetch(`${connection.url}/v1/inspect-driving`, {
      method: "POST", headers: connection.token ? { Authorization: `Bearer ${connection.token}` } : undefined,
      body: form, cache: "no-store", signal: AbortSignal.timeout(200_000),
    });
    if (!response.ok) throw new Error(`LivePortrait 远端 Driving Performance 校验失败（HTTP ${response.status}）`);
    return parseLivePortraitDrivingInspectionResult(JSON.stringify(await response.json()));
  }
  const invocation = buildLivePortraitDrivingInspectionInvocation({
    drivingPath,
    projectRoot,
    wrapperPython,
  });
  const { stdout } = await execFileAsync(invocation.command, invocation.args, {
    cwd: invocation.cwd,
    env: { ...process.env, PYTORCH_ENABLE_MPS_FALLBACK: "1" },
    timeout: 190_000,
    maxBuffer: 256 * 1024,
  });
  return parseLivePortraitDrivingInspectionResult(stdout);
}

export async function createOrReuseLivePortraitTask(input: LivePortraitTaskInput) {
  const active = store.activeTaskId ? store.tasks.get(store.activeTaskId) : undefined;
  if (active && (active.state === "queueing" || active.state === "processing")) {
    if (!livePortraitTaskMatchesInput(active, input)) {
      throw new LivePortraitTaskConflictError();
    }
    return { task: active, reused: true };
  }
  if (store.pendingCreation) {
    const pending = await store.pendingCreation;
    if (!livePortraitTaskMatchesInput(pending.task, input)) {
      throw new LivePortraitTaskConflictError();
    }
    return pending;
  }
  store.pendingCreation = createTask(input);
  try {
    return await store.pendingCreation;
  } finally {
    store.pendingCreation = undefined;
  }
}

async function createTask(input: LivePortraitTaskInput) {
  const projectRoot = path.resolve(input.projectRoot ?? process.cwd());
  const status = await inspectLivePortraitWorker(projectRoot);
  if (!status.ready) throw new Error(status.issues[0] || "LivePortrait Runtime 尚未就绪");
  let builtInDrivingPath: string | undefined;
  if (!input.drivingBytes || !input.drivingExtension) {
    const runtimeRoot = process.env.LIVEPORTRAIT_RUNTIME_ROOT ?? path.join(projectRoot, "models/liveportrait");
    const templatePath = resolveLivePortraitTemplate(input.driverId, projectRoot, runtimeRoot);
    if (!templatePath || !(await isRegularFile(templatePath))) throw new Error("所选 Driving Performance 素材不可用");
    builtInDrivingPath = templatePath;
  }
  const taskId = randomUUID();
  const taskRoot = path.resolve(input.taskRoot ?? defaultTaskRoot());
  const taskDir = path.join(taskRoot, taskId);
  const outputDir = path.join(taskDir, "output");
  await ensurePrivateTaskRoot(taskRoot);
  await mkdir(taskDir, { mode: 0o700 });
  await mkdir(outputDir, { mode: 0o700 });
  const sourcePath = path.join(taskDir, `source${input.sourceExtension}`);
  const configPath = path.join(taskDir, "liveportrait-motion-config.json");
  let drivingPath = builtInDrivingPath;
  try {
    await writeFile(sourcePath, input.sourceBytes, { flag: "wx", mode: 0o600 });
    await writeFile(configPath, JSON.stringify(input.livePortraitConfig, null, 2), { flag: "wx", mode: 0o600 });
    if (input.drivingBytes && input.drivingExtension) {
      drivingPath = path.join(taskDir, `driving${input.drivingExtension}`);
      await writeFile(drivingPath, input.drivingBytes, { flag: "wx", mode: 0o600 });
      const inspection = await inspectLivePortraitDrivingFile({
        drivingPath,
        projectRoot,
        wrapperPython: input.wrapperPython,
      });
      if (!inspection.eligible) {
        throw new LivePortraitDrivingValidationError(
          inspection.reason || "自定义参考视频不符合自然闭嘴动作要求",
        );
      }
    }
  } catch (error) {
    await rm(taskDir, { recursive: true, force: true });
    throw error;
  }
  if (!drivingPath) throw new Error("所选 Driving Performance 素材不可用");
  const now = new Date().toISOString();
  const task: LivePortraitTask = {
    id: taskId,
    state: "queueing",
    createdAt: now,
    updatedAt: now,
    driverId: input.drivingBytes ? "upload" : input.driverId,
    sourceName: input.sourceName,
    visualIdentityId: input.visualIdentityId,
    sourceSha256: sourceDigest(input.sourceBytes),
    livePortraitConfig: structuredClone(input.livePortraitConfig),
  };
  store.tasks.set(taskId, task);
  store.taskDirectories.set(taskId, { root: taskRoot, taskDir });
  store.activeTaskId = taskId;
  startRender(task, {
    sourcePath,
    drivingPath,
    outputDir,
    configPath,
    projectRoot,
    wrapperPython: input.wrapperPython,
    connection: await modelServiceConnection("liveportrait"),
  });
  return { task, reused: false };
}

export class LivePortraitTaskConflictError extends Error {
  constructor() {
    super("已有另一数字人身份的 LivePortrait 任务正在运行，请等待其结束");
    this.name = "LivePortraitTaskConflictError";
  }
}

export class LivePortraitDrivingValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "LivePortraitDrivingValidationError";
  }
}

export function livePortraitTaskMatchesInput(
  task: Pick<LivePortraitTask, "visualIdentityId" | "sourceSha256" | "driverId" | "livePortraitConfig">,
  input: Pick<LivePortraitTaskInput, "visualIdentityId" | "sourceBytes" | "driverId" | "drivingBytes" | "livePortraitConfig">,
) {
  return task.visualIdentityId === input.visualIdentityId
    && task.sourceSha256 === sourceDigest(input.sourceBytes)
    && task.driverId === (input.drivingBytes ? "upload" : input.driverId)
    && JSON.stringify(task.livePortraitConfig) === JSON.stringify(input.livePortraitConfig);
}

function sourceDigest(bytes: Uint8Array) {
  return createHash("sha256").update(bytes).digest("hex");
}

function startRender(
  task: LivePortraitTask,
  paths: { sourcePath: string; drivingPath: string; outputDir: string; configPath: string; projectRoot: string; wrapperPython?: string; connection: ModelServiceConnection },
) {
  if (paths.connection.url) {
    updateTask(task.id, { state: "processing" });
    void renderRemoteTask(task, paths);
    return;
  }
  const invocation = buildLivePortraitRenderInvocation({ ...paths });
  const child = spawn(invocation.command, invocation.args, {
    cwd: invocation.cwd,
    env: { ...process.env, PYTORCH_ENABLE_MPS_FALLBACK: "1" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  updateTask(task.id, { state: "processing" });
  collectProcessResult(child, task, paths.outputDir);
}

async function renderRemoteTask(task: LivePortraitTask, paths: {
  sourcePath: string; drivingPath: string; outputDir: string; configPath: string; connection: ModelServiceConnection;
}) {
  try {
    const sourceExtension = path.extname(paths.sourcePath).toLowerCase();
    const drivingExtension = path.extname(paths.drivingPath).toLowerCase();
    const sourceType = sourceExtension === ".png" ? "image/png" : sourceExtension === ".webp" ? "image/webp" : "image/jpeg";
    const drivingType = drivingExtension === ".webm" ? "video/webm" : drivingExtension === ".mov" ? "video/quicktime" : "video/mp4";
    const output = await runInferenceServiceJob({
      baseUrl: paths.connection.url, token: paths.connection.token, jobId: task.id,
      sourceVideo: await readFile(paths.sourcePath), referenceAudio: await readFile(paths.drivingPath),
      sourceField: "source_image", referenceField: "driving_video",
      sourceName: `source${sourceExtension}`, referenceName: `driving${drivingExtension}`,
      sourceType, referenceType: drivingType, configJson: await readFile(paths.configPath, "utf8"),
      rightsConfirmed: true, timeoutMs: 960_000,
    });
    const resultPath = path.join(paths.outputDir, "output.mp4");
    await writeFile(resultPath, output, { flag: "wx", mode: 0o600 });
    finishTask(task.id, { state: "success", resultPath, device: "remote" });
  } catch (error) {
    console.error("LivePortrait remote render failed", { taskId: task.id, error });
    finishTask(task.id, { state: "failed", error: "LivePortrait 远端渲染失败，请检查模型服务日志" });
  }
}

function collectProcessResult(child: ChildProcess, task: LivePortraitTask, outputDir: string) {
  let stdout = "";
  let stderr = "";
  let settled = false;
  child.stdout?.on("data", (chunk) => { stdout = appendBounded(stdout, String(chunk)); });
  child.stderr?.on("data", (chunk) => { stderr = appendBounded(stderr, String(chunk)); });
  child.once("error", () => {
    if (settled) return;
    settled = true;
    finishTask(task.id, { state: "failed", error: "LivePortrait Worker 启动失败" });
  });
  child.once("close", async (code) => {
    if (settled) return;
    settled = true;
    if (code !== 0) {
      console.error("LivePortrait render failed", { taskId: task.id, code, stderr });
      finishTask(task.id, { state: "failed", error: `LivePortrait 渲染失败（退出码 ${code ?? "unknown"}）` });
      return;
    }
    try {
      const result = parseLivePortraitRenderResult(stdout);
      if (typeof result.output !== "string") throw new Error("missing output path");
      const resultPath = await realpath(path.resolve(result.output));
      const allowedRoot = await realpath(path.resolve(outputDir));
      const relativeResult = path.relative(allowedRoot, resultPath);
      if (!relativeResult || relativeResult.startsWith("..") || path.isAbsolute(relativeResult)) {
        throw new Error("output escaped task directory");
      }
      await chmod(resultPath, 0o600);
      finishTask(task.id, {
        state: "success",
        resultPath,
        renderSeconds: typeof result.render_seconds === "number" ? result.render_seconds : undefined,
        device: typeof result.device === "string" ? result.device : undefined,
      });
    } catch (error) {
      console.error("LivePortrait result metadata is invalid", { taskId: task.id, error });
      finishTask(task.id, { state: "failed", error: "LivePortrait 结果校验失败" });
    }
  });
}

export function parseLivePortraitRenderResult(stdout: string) {
  const resultLine = stdout.trim().split(/[\r\n]+/).reverse()
    .find((line) => line.trim().startsWith("{"));
  if (!resultLine) throw new Error("missing result metadata");
  return JSON.parse(resultLine) as { output?: unknown; render_seconds?: unknown; device?: unknown };
}

export function parseLivePortraitDrivingInspectionResult(stdout: string): LivePortraitDrivingInspection {
  const resultLine = stdout.trim().split(/[\r\n]+/).reverse()
    .find((line) => line.trim().startsWith("{"));
  if (!resultLine) throw new Error("missing driving inspection metadata");
  const payload = JSON.parse(resultLine) as Record<string, unknown>;
  if (
    typeof payload.eligible !== "boolean"
    || (payload.reason !== null && payload.reason !== undefined && typeof payload.reason !== "string")
    || typeof payload.duration_seconds !== "number"
    || typeof payload.sample_count !== "number"
    || typeof payload.median_ratio !== "number"
    || typeof payload.maximum_ratio !== "number"
  ) {
    throw new Error("invalid driving inspection metadata");
  }
  return {
    eligible: payload.eligible,
    reason: typeof payload.reason === "string" ? payload.reason : undefined,
    durationSeconds: payload.duration_seconds,
    sampleCount: payload.sample_count,
    medianRatio: payload.median_ratio,
    maximumRatio: payload.maximum_ratio,
  };
}

export function getLivePortraitTask(taskId: string) {
  return store.tasks.get(taskId);
}

export function retainLivePortraitTaskArtifact(taskId: string) {
  const task = store.tasks.get(taskId);
  if (task?.state !== "success" || !task.resultPath || store.cleanupDue.has(taskId)) return undefined;
  store.readerCounts.set(taskId, (store.readerCounts.get(taskId) ?? 0) + 1);
  let released = false;
  return () => {
    if (released) return;
    released = true;
    const readers = Math.max(0, (store.readerCounts.get(taskId) ?? 1) - 1);
    if (readers) store.readerCounts.set(taskId, readers);
    else store.readerCounts.delete(taskId);
    if (!readers && store.cleanupDue.has(taskId)) void cleanupTask(taskId);
  };
}

export function resetLivePortraitWorkerForTest() {
  for (const timer of store.cleanupTimers.values()) clearTimeout(timer);
  store.tasks.clear();
  store.activeTaskId = undefined;
  store.pendingCreation = undefined;
  store.taskDirectories.clear();
  store.readerCounts.clear();
  store.cleanupDue.clear();
  store.cleanupTimers.clear();
}

function updateTask(taskId: string, patch: Partial<LivePortraitTask>) {
  const current = store.tasks.get(taskId);
  if (!current) return;
  Object.assign(current, patch, { updatedAt: new Date().toISOString() });
}

function finishTask(taskId: string, patch: Partial<LivePortraitTask>) {
  updateTask(taskId, patch);
  if (store.activeTaskId === taskId) store.activeTaskId = undefined;
  scheduleTaskCleanup(taskId, patch.state === "success" ? SUCCESS_TASK_TTL_MS : FAILED_TASK_TTL_MS);
}

function scheduleTaskCleanup(taskId: string, delayMs: number) {
  const previous = store.cleanupTimers.get(taskId);
  if (previous) clearTimeout(previous);
  const timer = setTimeout(() => {
    store.cleanupTimers.delete(taskId);
    store.cleanupDue.add(taskId);
    if ((store.readerCounts.get(taskId) ?? 0) > 0) {
      return;
    }
    void cleanupTask(taskId);
  }, delayMs);
  timer.unref?.();
  store.cleanupTimers.set(taskId, timer);
}

async function cleanupTask(taskId: string) {
  const directory = store.taskDirectories.get(taskId);
  if ((store.readerCounts.get(taskId) ?? 0) > 0) {
    store.cleanupDue.add(taskId);
    return;
  }
  if (directory && await isSafeTaskDirectory(directory.root, directory.taskDir)) {
    try {
      await rm(directory.taskDir, { recursive: true, force: true });
    } catch (error) {
      console.error("Failed to clean up LivePortrait task directory", { taskId, error });
      scheduleTaskCleanup(taskId, FAILED_TASK_TTL_MS);
      return;
    }
  }
  store.tasks.delete(taskId);
  store.taskDirectories.delete(taskId);
  store.readerCounts.delete(taskId);
  store.cleanupDue.delete(taskId);
}

export function isPathInside(root: string, candidate: string) {
  const relative = path.relative(path.resolve(root), path.resolve(candidate));
  return Boolean(relative) && !relative.startsWith("..") && !path.isAbsolute(relative);
}

function defaultTaskRoot() {
  return path.resolve(process.env.LIVEPORTRAIT_TASK_ROOT ?? path.join(os.tmpdir(), "openrealtime-liveportrait"));
}

async function ensurePrivateTaskRoot(taskRoot: string) {
  await mkdir(taskRoot, { recursive: true, mode: 0o700 });
  const rootStats = await lstat(taskRoot);
  if (!rootStats.isDirectory() || rootStats.isSymbolicLink()) {
    throw new Error("LivePortrait 任务根目录必须是实体目录");
  }
  if (typeof process.getuid === "function" && rootStats.uid !== process.getuid()) {
    throw new Error("LivePortrait 任务根目录不属于当前进程用户");
  }
  await chmod(taskRoot, 0o700);
}

async function isSafeTaskDirectory(taskRoot: string, taskDir: string) {
  if (!isPathInside(taskRoot, taskDir) || !TASK_ID_PATTERN.test(path.basename(taskDir))) return false;
  try {
    const [rootStats, taskStats] = await Promise.all([lstat(taskRoot), lstat(taskDir)]);
    if (!rootStats.isDirectory() || rootStats.isSymbolicLink() || !taskStats.isDirectory() || taskStats.isSymbolicLink()) return false;
    const [realRoot, realTaskDir] = await Promise.all([realpath(taskRoot), realpath(taskDir)]);
    return isPathInside(realRoot, realTaskDir);
  } catch {
    return false;
  }
}

export async function reconcileLivePortraitTaskRoot(taskRoot = defaultTaskRoot()) {
  let rootStats;
  try {
    rootStats = await lstat(taskRoot);
  } catch {
    return;
  }
  if (!rootStats.isDirectory() || rootStats.isSymbolicLink()) return;
  if (typeof process.getuid === "function" && rootStats.uid !== process.getuid()) return;
  await chmod(taskRoot, 0o700);
  const entries = await readdir(taskRoot, { withFileTypes: true });
  await Promise.all(entries.map(async (entry) => {
    if (!entry.isDirectory() || entry.isSymbolicLink() || !TASK_ID_PATTERN.test(entry.name)) return;
    const taskDir = path.join(taskRoot, entry.name);
    if (store.tasks.has(entry.name) || store.taskDirectories.has(entry.name) || !await isSafeTaskDirectory(taskRoot, taskDir)) return;
    const taskStats = await stat(taskDir);
    const remainingMs = Math.max(0, SUCCESS_TASK_TTL_MS - (Date.now() - taskStats.mtimeMs));
    store.taskDirectories.set(entry.name, { root: taskRoot, taskDir });
    if (remainingMs === 0) {
      store.cleanupDue.add(entry.name);
      await cleanupTask(entry.name);
    } else {
      scheduleTaskCleanup(entry.name, remainingMs);
    }
  }));
}

function appendBounded(current: string, next: string) {
  const combined = current + next;
  return combined.length > MAX_LOG_CHARS ? combined.slice(-MAX_LOG_CHARS) : combined;
}

async function isRegularFile(filePath: string | null) {
  if (!filePath) return false;
  try {
    return (await stat(filePath)).isFile();
  } catch {
    return false;
  }
}

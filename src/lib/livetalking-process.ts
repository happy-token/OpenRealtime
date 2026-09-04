import { spawn, type ChildProcess } from "node:child_process";
import net from "node:net";
import path from "node:path";

interface LiveTalkingProcessState {
  child: ChildProcess | null;
  starting: Promise<void> | null;
}

const processGlobal = globalThis as typeof globalThis & {
  __openRealtimeLiveTalkingProcesses?: Map<string, LiveTalkingProcessState>;
};

function state(key: string): LiveTalkingProcessState {
  processGlobal.__openRealtimeLiveTalkingProcesses ??= new Map();
  const current = processGlobal.__openRealtimeLiveTalkingProcesses.get(key)
    ?? { child: null, starting: null };
  processGlobal.__openRealtimeLiveTalkingProcesses.set(key, current);
  return current;
}

export function resolveWav2LipInferenceStride(
  environment: Record<string, string | undefined>,
): 1 | 2 {
  const configured = environment.OPENREALTIME_WAV2LIP_INFERENCE_STRIDE ?? "2";
  if (configured === "1" || configured === "2") return Number(configured) as 1 | 2;
  throw new Error("OPENREALTIME_WAV2LIP_INFERENCE_STRIDE must be 1 or 2");
}

export async function ensureLiveTalkingProcess(
  projectRoot = process.cwd(),
  port = 8010,
  modelSize: 256 | 96 = 256,
): Promise<void> {
  if (await portIsOpen(port)) return;
  const current = state(`${modelSize}:${port}`);
  if (current.starting) return current.starting;
  current.starting = startProcess(projectRoot, port, modelSize, current).finally(() => {
    current.starting = null;
  });
  return current.starting;
}

export function stopLiveTalkingProcess(): void {
  for (const current of processGlobal.__openRealtimeLiveTalkingProcesses?.values() ?? []) {
    const child = current.child;
    current.child = null;
    if (child && child.exitCode === null && child.signalCode === null) child.kill("SIGTERM");
  }
}

async function startProcess(
  projectRoot: string,
  port: number,
  modelSize: 256 | 96,
  current: LiveTalkingProcessState,
): Promise<void> {
  const python = path.join(projectRoot, "models/livetalking/.venv/bin/python");
  const launcher = path.join(projectRoot, "scripts/livetalking_provider.py");
  const inferenceStride = modelSize === 256 ? resolveWav2LipInferenceStride(process.env) : 1;
  const child = spawn(python, [
    launcher,
    "serve",
    "--runtime-root",
    path.join(projectRoot, "models/livetalking"),
    "--avatar-id",
    modelSize === 256 ? "shuchang256" : "shuchang",
    "--port",
    String(port),
    "--inference-stride",
    String(inferenceStride),
    "--model-size",
    String(modelSize),
  ], {
    cwd: projectRoot,
    env: process.env,
    stdio: "inherit",
  });
  current.child = child;
  const exited = new Promise<never>((_, reject) => {
    child.once("error", reject);
    child.once("exit", (code, signal) => {
      if (current.child === child) current.child = null;
      reject(new Error(`LiveTalking exited before readiness (${code ?? signal ?? "unknown"})`));
    });
  });
  await Promise.race([waitForPort(port, 120_000), exited]);
}

async function waitForPort(port: number, timeoutMs: number): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await portIsOpen(port)) return;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  stopLiveTalkingProcess();
  throw new Error("LiveTalking startup timed out");
}

function portIsOpen(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const socket = net.createConnection({ host: "127.0.0.1", port });
    const finish = (open: boolean) => {
      socket.removeAllListeners();
      socket.destroy();
      resolve(open);
    };
    socket.setTimeout(300);
    socket.once("connect", () => finish(true));
    socket.once("error", () => finish(false));
    socket.once("timeout", () => finish(false));
  });
}

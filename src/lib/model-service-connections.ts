import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";

export const MODEL_SERVICE_KINDS = ["lipforcing", "musetalk", "wav2lip", "liveportrait"] as const;
export type ModelServiceKind = (typeof MODEL_SERVICE_KINDS)[number];
export type ModelServiceConnection = { url: string; token: string };
type ConnectionCatalog = Partial<Record<ModelServiceKind, ModelServiceConnection>>;

const EMPTY: ModelServiceConnection = { url: "", token: "" };

export function isModelServiceKind(value: unknown): value is ModelServiceKind {
  return typeof value === "string" && MODEL_SERVICE_KINDS.includes(value as ModelServiceKind);
}

export function normalizeModelServiceUrl(value: unknown): string {
  if (value === "") return "";
  if (typeof value !== "string" || value.length > 2048 || value !== value.trim()) throw new Error("请输入有效的服务 URL");
  let parsed: URL;
  try { parsed = new URL(value); }
  catch { throw new Error("请输入有效的服务 URL"); }
  if (!["http:", "https:"].includes(parsed.protocol) || !parsed.hostname || parsed.username || parsed.password
    || parsed.search || parsed.hash || /[\x00-\x1f\x7f]/.test(value)) {
    throw new Error("服务 URL 只支持不含凭证、查询参数的 HTTP(S) 地址");
  }
  return parsed.toString().replace(/\/$/, "");
}

export function normalizeModelServiceToken(value: unknown): string {
  if (typeof value !== "string" || value.length > 512 || value !== value.trim() || /[\x00-\x1f\x7f]/.test(value)) {
    throw new Error("访问令牌格式无效");
  }
  return value;
}

function catalogPath(): string {
  return path.join(process.cwd(), ".openrealtime", "model-service-connections.json");
}

async function readCatalog(): Promise<ConnectionCatalog> {
  try {
    const parsed: unknown = JSON.parse(await readFile(catalogPath(), "utf8"));
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("服务配置文件格式无效");
    const catalog: ConnectionCatalog = {};
    for (const kind of MODEL_SERVICE_KINDS) {
      const value = (parsed as Record<string, unknown>)[kind];
      if (!value || typeof value !== "object") continue;
      const entry = value as Record<string, unknown>;
      if (typeof entry.url === "string" && typeof entry.token === "string") {
        catalog[kind] = { url: normalizeModelServiceUrl(entry.url), token: normalizeModelServiceToken(entry.token) };
      }
    }
    return catalog;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return {};
    throw error;
  }
}

export async function modelServiceConnections(): Promise<Record<ModelServiceKind, ModelServiceConnection>> {
  const catalog = await readCatalog();
  return Object.fromEntries(MODEL_SERVICE_KINDS.map((kind) => [kind, catalog[kind] ?? EMPTY])) as Record<ModelServiceKind, ModelServiceConnection>;
}

export async function modelServiceConnection(kind: ModelServiceKind): Promise<ModelServiceConnection> {
  const catalog = await readCatalog();
  return catalog[kind] ?? EMPTY;
}

let writeTail: Promise<void> = Promise.resolve();

export async function saveModelServiceConnection(kind: ModelServiceKind, input: { url: string; token?: string | null }): Promise<ModelServiceConnection> {
  const url = normalizeModelServiceUrl(input.url);
  const token = input.token === undefined ? undefined : normalizeModelServiceToken(input.token ?? "");
  const operation = writeTail.catch(() => undefined).then(async () => {
    const catalog = await readCatalog();
    const next = { url, token: url ? (token ?? (catalog[kind]?.url === url ? catalog[kind]?.token : "") ?? "") : "" };
    catalog[kind] = next;
    const target = catalogPath();
    await mkdir(path.dirname(target), { recursive: true, mode: 0o700 });
    const temporary = `${target}.${randomUUID()}.tmp`;
    await writeFile(temporary, JSON.stringify(catalog, null, 2), { flag: "wx", mode: 0o600 });
    await rename(temporary, target);
    return next;
  });
  writeTail = operation.then(() => undefined);
  return operation;
}

export async function probeModelService(kind: ModelServiceKind, connection: ModelServiceConnection): Promise<{ ready: boolean; message: string }> {
  if (!connection.url) return { ready: false, message: "尚未配置 URL" };
  const base = normalizeModelServiceUrl(connection.url);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 8_000);
  try {
    const response = await fetch(`${base}/health`, {
      headers: connection.token ? { Authorization: `Bearer ${connection.token}` } : undefined,
      redirect: "manual", cache: "no-store", signal: controller.signal,
    });
    if (!response.ok) return { ready: false, message: `健康检查返回 HTTP ${response.status}` };
    const payload = await response.json() as { status?: unknown; model?: unknown };
    const expectedModel = kind === "lipforcing" ? "lipforcing-14b" : kind;
    if (payload.status !== "ok" || payload.model !== expectedModel) {
      return { ready: false, message: "连接成功，但不是对应的模型服务或模型未就绪" };
    }
    return { ready: true, message: "连接正常，模型已就绪" };
  } catch {
    return { ready: false, message: "连接失败或检查超时；请确认 URL 对应用服务器可达" };
  } finally {
    clearTimeout(timer);
  }
}

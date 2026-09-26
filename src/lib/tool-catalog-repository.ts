import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { withAvatarCatalogLock } from "./avatar-catalog-lock";
import { isToolEffect, isToolKind, isToolRisk, type ToolKind, type ToolRecord } from "./tool-records";

const TOOL_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{1,159}$/;
const FUNCTION_NAME = /^[A-Za-z_][A-Za-z0-9_]{1,63}$/;

const BUILTIN_TOOLS: ToolRecord[] = [
  builtinTool("tool-current-time", "当前时间", "读取当前日期、时间与时区。", "get_current_datetime"),
  builtinTool("tool-web-search", "联网搜索", "搜索公开网页并返回与问题相关的资料。", "search_web"),
];

export async function listTools(root = repositoryRoot()): Promise<ToolRecord[]> {
  const stored = await readCatalog(root);
  return [...BUILTIN_TOOLS, ...stored].sort((left, right) => Number(right.builtin) - Number(left.builtin) || right.updated_at.localeCompare(left.updated_at));
}

export async function createTool(input: {
  displayName: string;
  description: string;
  kind: Exclude<ToolKind, "builtin">;
  functionName: string;
  inputSchema: Record<string, unknown>;
  endpoint?: string | null;
  method?: "GET" | "POST" | null;
  mcpTransport?: "stdio" | "streamable-http" | null;
  riskLevel?: ToolRecord["risk_level"];
  effect?: ToolRecord["effect"];
}, root = repositoryRoot()): Promise<ToolRecord> {
  return withAvatarCatalogLock(root, async () => {
    const records = await readCatalog(root);
    const now = new Date().toISOString();
    const functionName = normalizeFunctionName(input.functionName);
    if (records.some(item => item.function_name === functionName) || BUILTIN_TOOLS.some(item => item.function_name === functionName) || functionName === "search_knowledge_base") throw new Error("函数名称已存在");
    const record: ToolRecord = {
      tool_id: `tool-${randomUUID()}`,
      display_name: normalizeText(input.displayName, 80, "请填写工具名称"),
      description: normalizeText(input.description, 400, "请填写工具说明"),
      kind: input.kind,
      enabled: true,
      builtin: false,
      public_enabled: false,
      risk_level: normalizeRisk(input.riskLevel),
      effect: normalizeEffect(input.effect),
      function_name: functionName,
      input_schema: normalizeSchema(input.inputSchema),
      endpoint: normalizeEndpoint(input.kind, input.endpoint),
      method: input.kind === "api" ? input.method ?? "POST" : null,
      mcp_transport: input.kind === "mcp" ? "streamable-http" : null,
      created_at: now,
      updated_at: now,
    };
    await writeCatalog(root, [...records, record]);
    return record;
  });
}

export async function setToolEnabled(toolId: string, enabled: boolean, root = repositoryRoot()) {
  validateToolId(toolId);
  if (BUILTIN_TOOLS.some((tool) => tool.tool_id === toolId)) {
    return { ...BUILTIN_TOOLS.find((tool) => tool.tool_id === toolId)!, enabled };
  }
  return withAvatarCatalogLock(root, async () => {
    const records = await readCatalog(root);
    const current = records.find((tool) => tool.tool_id === toolId);
    if (!current) throw new Error("找不到这个工具");
    const next = { ...current, enabled, updated_at: new Date().toISOString() };
    await writeCatalog(root, records.map((tool) => tool.tool_id === toolId ? next : tool));
    return next;
  });
}

export async function setToolPublicEnabled(toolId: string, publicEnabled: boolean, root = repositoryRoot()) {
  validateToolId(toolId);
  return withAvatarCatalogLock(root, async () => {
    const records = await readCatalog(root);
    const current = records.find(item => item.tool_id === toolId);
    if (!current) throw new Error("找不到这个工具");
    if (publicEnabled && !current.endpoint) throw new Error("工具缺少执行服务地址");
    const next = { ...current, public_enabled: publicEnabled, updated_at: new Date().toISOString() };
    await writeCatalog(root, records.map(item => item.tool_id === toolId ? next : item));
    return next;
  });
}

export async function updateTool(toolId: string, input: {
  displayName: string; description: string; kind: Exclude<ToolKind, "builtin">;
  functionName: string; inputSchema: Record<string, unknown>; endpoint: string | null;
  method?: "GET" | "POST" | null;
  riskLevel?: ToolRecord["risk_level"];
  effect?: ToolRecord["effect"];
}, root = repositoryRoot()): Promise<ToolRecord> {
  validateToolId(toolId);
  return withAvatarCatalogLock(root, async () => {
    const records = await readCatalog(root);
    const current = records.find(item => item.tool_id === toolId);
    if (!current) throw new Error("找不到这个工具");
    const functionName = normalizeFunctionName(input.functionName);
    if (records.some(item => item.tool_id !== toolId && item.function_name === functionName) || BUILTIN_TOOLS.some(item => item.function_name === functionName) || functionName === "search_knowledge_base") throw new Error("函数名称已存在");
    const updated: ToolRecord = {
      ...current,
      display_name: normalizeText(input.displayName, 80, "请填写工具名称"),
      description: normalizeText(input.description, 400, "请填写工具说明"),
      kind: input.kind,
      function_name: functionName,
      input_schema: normalizeSchema(input.inputSchema),
      endpoint: normalizeEndpoint(input.kind, input.endpoint),
      method: input.kind === "api" ? input.method ?? "POST" : null,
      risk_level: normalizeRisk(input.riskLevel),
      effect: normalizeEffect(input.effect),
      mcp_transport: input.kind === "mcp" ? "streamable-http" : null,
      updated_at: new Date().toISOString(),
    };
    await writeCatalog(root, records.map(item => item.tool_id === toolId ? updated : item));
    return updated;
  });
}

function builtinTool(toolId: string, displayName: string, description: string, functionName: string): ToolRecord {
  return {
    tool_id: toolId,
    display_name: displayName,
    description,
    kind: "builtin",
    enabled: true,
    builtin: true,
    function_name: functionName,
    input_schema: { type: "object", properties: {} },
    endpoint: null,
    method: null,
    mcp_transport: null,
    created_at: new Date(0).toISOString(),
    updated_at: new Date(0).toISOString(),
  };
}

function normalizeText(value: string, maxLength: number, emptyMessage: string) {
  const normalized = value.trim();
  if (!normalized) throw new Error(emptyMessage);
  if (normalized.length > maxLength || /[\r\n]/.test(normalized)) throw new Error("工具文本无效");
  return normalized;
}

function normalizeFunctionName(value: string) {
  const normalized = value.trim();
  if (!FUNCTION_NAME.test(normalized)) throw new Error("函数名称无效");
  return normalized;
}

function normalizeSchema(value: Record<string, unknown>) {
  if (value.type !== "object" || (value.properties !== undefined && (!value.properties || typeof value.properties !== "object" || Array.isArray(value.properties)))) {
    throw new Error("输入 Schema 必须是 JSON object schema");
  }
  return value;
}

function normalizeEndpoint(kind: Exclude<ToolKind, "builtin">, value?: string | null) {
  const endpoint = value?.trim() ?? "";
  if (!endpoint) throw new Error(kind === "mcp" ? "请填写 MCP 服务地址" : "请填写执行服务地址");
  if (endpoint.length > 500 || /[\r\n]/.test(endpoint)) throw new Error("服务地址无效");
  const url = new URL(endpoint);
  if ((url.protocol !== "http:" && url.protocol !== "https:") || url.username || url.password || url.hash) throw new Error("服务地址必须是无凭据的 HTTP 或 HTTPS URL");
  return endpoint;
}

function normalizeRisk(value: ToolRecord["risk_level"]) {
  if (value === undefined) return "medium";
  if (!isToolRisk(value)) throw new Error("工具风险等级无效");
  return value;
}

function normalizeEffect(value: ToolRecord["effect"]) {
  if (value === undefined) return "read_sensitive";
  if (!isToolEffect(value)) throw new Error("工具作用类型无效");
  return value;
}

function validateToolId(toolId: string) {
  if (!TOOL_ID.test(toolId)) throw new Error("工具 ID 无效");
}

function repositoryRoot() {
  return path.resolve(process.env.TOOL_CATALOG_DIR?.trim() || path.join(process.cwd(), ".openrealtime", "tool-catalog"));
}

function catalogPath(root: string) {
  return path.join(root, "tools.json");
}

async function readCatalog(root: string): Promise<ToolRecord[]> {
  try {
    const value = JSON.parse(await readFile(catalogPath(root), "utf8")) as unknown;
    if (!Array.isArray(value) || !value.every(isStoredTool)) throw new Error("工具目录结构异常");
    return value;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw error;
  }
}

async function writeCatalog(root: string, records: ToolRecord[]) {
  await mkdir(root, { recursive: true });
  const temporary = path.join(root, `tools.${randomUUID()}.tmp`);
  await writeFile(temporary, JSON.stringify(records, null, 2), { flag: "wx", mode: 0o600 });
  await rename(temporary, catalogPath(root));
}

function isStoredTool(value: unknown): value is ToolRecord {
  if (!value || typeof value !== "object") return false;
  const tool = value as ToolRecord;
  return TOOL_ID.test(tool.tool_id)
    && typeof tool.display_name === "string"
    && typeof tool.description === "string"
    && isToolKind(tool.kind)
    && tool.kind !== "builtin"
    && tool.builtin === false
    && typeof tool.enabled === "boolean"
    && (tool.public_enabled === undefined || typeof tool.public_enabled === "boolean")
    && (tool.risk_level === undefined || isToolRisk(tool.risk_level))
    && (tool.effect === undefined || isToolEffect(tool.effect))
    && FUNCTION_NAME.test(tool.function_name)
    && Boolean(tool.input_schema) && typeof tool.input_schema === "object" && !Array.isArray(tool.input_schema)
    && (tool.endpoint === null || typeof tool.endpoint === "string")
    && (tool.method === null || tool.method === "GET" || tool.method === "POST")
    && (tool.mcp_transport === null || tool.mcp_transport === "stdio" || tool.mcp_transport === "streamable-http")
    && typeof tool.created_at === "string"
    && typeof tool.updated_at === "string";
}

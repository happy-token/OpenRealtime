import { readJsonResponse } from "./http-json-response";
import type { ToolKind, ToolRecord } from "./tool-records";

export async function fetchTools(signal?: AbortSignal) {
  const response = await fetch("/api/tools", { cache: "no-store", signal });
  const payload = await readJsonResponse<{ tools?: ToolRecord[]; error?: string }>(response, "工具目录读取失败");
  if (!response.ok || !payload.tools) throw new Error(payload.error || "工具目录读取失败");
  return payload.tools;
}

export async function createTool(input: {
  displayName: string;
  description: string;
  kind: Exclude<ToolKind, "builtin">;
  functionName: string;
  inputSchema: Record<string, unknown>;
  endpoint: string | null;
  method: "GET" | "POST" | null;
  mcpTransport: "stdio" | "streamable-http" | null;
  riskLevel?: ToolRecord["risk_level"];
  effect?: ToolRecord["effect"];
}) {
  const response = await fetch("/api/tools", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  const payload = await readJsonResponse<{ tool?: ToolRecord; error?: string }>(response, "工具创建失败");
  if (!response.ok || !payload.tool) throw new Error(payload.error || "工具创建失败");
  return payload.tool;
}

export async function setToolEnabled(toolId: string, enabled: boolean) {
  const response = await fetch(`/api/tools/${encodeURIComponent(toolId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  const payload = await readJsonResponse<{ tool?: ToolRecord; error?: string }>(response, "工具更新失败");
  if (!response.ok || !payload.tool) throw new Error(payload.error || "工具更新失败");
  return payload.tool;
}

export async function setToolPublicEnabled(toolId: string, publicEnabled: boolean) {
  const response = await fetch(`/api/tools/${encodeURIComponent(toolId)}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ publicEnabled }),
  });
  const payload = await readJsonResponse<{ tool?: ToolRecord; error?: string }>(response, "工具更新失败");
  if (!response.ok || !payload.tool) throw new Error(payload.error || "工具更新失败");
  return payload.tool;
}

export async function updateTool(toolId: string, input: {
  displayName: string; description: string; kind: Exclude<ToolKind, "builtin">;
  functionName: string; inputSchema: Record<string, unknown>; endpoint: string;
  method: "GET" | "POST";
  riskLevel?: ToolRecord["risk_level"];
  effect?: ToolRecord["effect"];
}) {
  const response = await fetch(`/api/tools/${encodeURIComponent(toolId)}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(input),
  });
  const payload = await readJsonResponse<{ tool?: ToolRecord; error?: string }>(response, "工具更新失败");
  if (!response.ok || !payload.tool) throw new Error(payload.error || "工具更新失败");
  return payload.tool;
}

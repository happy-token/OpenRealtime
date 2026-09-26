import { authorizeAvatarAssetRequest, jsonError } from "@/lib/avatar-assets-server";
import { createTool, listTools } from "@/lib/tool-catalog-repository";
import { isToolEffect, isToolKind, isToolRisk } from "@/lib/tool-records";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: Request) {
  if (!authorizeAvatarAssetRequest(request, false)) return jsonError("不允许读取工具目录", 403);
  try {
    return Response.json({ tools: await listTools() }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    console.error("Failed to read tool catalog", error);
    return jsonError("工具目录暂时不可用", 503);
  }
}

export async function POST(request: Request) {
  if (!authorizeAvatarAssetRequest(request, true)) return jsonError("不允许创建工具", 403);
  try {
    const payload = await request.json() as Record<string, unknown>;
    if (typeof payload.displayName !== "string"
      || typeof payload.description !== "string"
      || !isToolKind(payload.kind)
      || payload.kind === "builtin"
      || typeof payload.functionName !== "string"
      || !payload.inputSchema
      || typeof payload.inputSchema !== "object"
      || Array.isArray(payload.inputSchema)) {
      return jsonError("工具配置无效", 400);
    }
    if ((payload.riskLevel !== undefined && !isToolRisk(payload.riskLevel)) || (payload.effect !== undefined && !isToolEffect(payload.effect))) return jsonError("工具风险配置无效", 400);
    const tool = await createTool({
      displayName: payload.displayName,
      description: payload.description,
      kind: payload.kind,
      functionName: payload.functionName,
      inputSchema: payload.inputSchema as Record<string, unknown>,
      endpoint: typeof payload.endpoint === "string" ? payload.endpoint : null,
      method: payload.method === "GET" ? "GET" : "POST",
      mcpTransport: payload.mcpTransport === "stdio" ? "stdio" : "streamable-http",
      riskLevel: payload.riskLevel as "low" | "medium" | "high" | "critical" | undefined,
      effect: payload.effect as "read_public" | "read_sensitive" | "write_reversible" | "write_irreversible" | "execute_code" | "communicate_external" | "spend_or_transfer" | "control_device" | undefined,
    });
    return Response.json({ tool }, { status: 201, headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const message = error instanceof Error ? error.message : "工具创建失败";
    return jsonError(message, /无效|填写|必须/.test(message) ? 400 : 503);
  }
}

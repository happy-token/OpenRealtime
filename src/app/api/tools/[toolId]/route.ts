import { authorizeAvatarAssetRequest, jsonError } from "@/lib/avatar-assets-server";
import { setToolEnabled, setToolPublicEnabled, updateTool } from "@/lib/tool-catalog-repository";
import { isToolEffect, isToolKind, isToolRisk } from "@/lib/tool-records";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

type Context = { params: Promise<{ toolId: string }> };

export async function PATCH(request: Request, context: Context) {
  if (!authorizeAvatarAssetRequest(request, true)) return jsonError("不允许修改工具", 403);
  try {
    const payload = await request.json() as Record<string, unknown>;
    const { toolId } = await context.params;
    const tool = typeof payload.enabled === "boolean"
      ? await setToolEnabled(toolId, payload.enabled)
      : typeof payload.publicEnabled === "boolean"
        ? await setToolPublicEnabled(toolId, payload.publicEnabled)
      : isToolKind(payload.kind) && payload.kind !== "builtin" && typeof payload.displayName === "string" && typeof payload.description === "string" && typeof payload.functionName === "string" && typeof payload.endpoint === "string" && Boolean(payload.inputSchema) && typeof payload.inputSchema === "object" && !Array.isArray(payload.inputSchema) && (payload.riskLevel === undefined || isToolRisk(payload.riskLevel)) && (payload.effect === undefined || isToolEffect(payload.effect))
        ? await updateTool(toolId, { displayName: payload.displayName, description: payload.description, kind: payload.kind, functionName: payload.functionName, inputSchema: payload.inputSchema as Record<string, unknown>, endpoint: payload.endpoint, method: payload.method === "GET" ? "GET" : "POST", riskLevel: payload.riskLevel as "low" | "medium" | "high" | "critical" | undefined, effect: payload.effect as "read_public" | "read_sensitive" | "write_reversible" | "write_irreversible" | "execute_code" | "communicate_external" | "spend_or_transfer" | "control_device" | undefined })
        : null;
    if (!tool) return jsonError("工具配置无效", 400);
    return Response.json({ tool }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const message = error instanceof Error ? error.message : "工具更新失败";
    return jsonError(message, message.includes("找不到") ? 404 : message.includes("无效") ? 400 : 503);
  }
}

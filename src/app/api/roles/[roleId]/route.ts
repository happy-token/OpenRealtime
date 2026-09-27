import { authorizeAvatarAssetRequest, jsonError } from "@/lib/avatar-assets-server";
import { deleteRole, findRole, updateRole } from "@/lib/role-catalog-repository";
import { isRoleDefaultSelections, isRolePresentationMode, isRoleVoiceDialect } from "@/lib/role-records";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

type Context = { params: Promise<{ roleId: string }> };

export async function GET(request: Request, context: Context) {
  if (!authorizeAvatarAssetRequest(request, false)) return jsonError("不允许读取角色", 403);
  try {
    const role = await findRole((await context.params).roleId);
    return role
      ? Response.json({ role }, { headers: { "Cache-Control": "no-store" } })
      : jsonError("角色不存在", 404);
  } catch (error) {
    const message = error instanceof Error ? error.message : "角色读取失败";
    return jsonError(message, message.includes("无效") ? 400 : 503);
  }
}

export async function PATCH(request: Request, context: Context) {
  if (!authorizeAvatarAssetRequest(request, true)) return jsonError("不允许修改角色", 403);
  try {
    const payload = await request.json() as Record<string, unknown>;
    if (typeof payload.displayName !== "string"
      || (payload.voiceProvider !== "bailian" && payload.voiceProvider !== "doubao")
      || typeof payload.voiceId !== "string"
      || !(payload.voiceDialect === undefined || isRoleVoiceDialect(payload.voiceDialect))
      || !(payload.asrProvider === undefined || payload.asrProvider === null || payload.asrProvider === "doubao" || payload.asrProvider === "dashscope")
      || !(payload.llmProvider === undefined || payload.llmProvider === null || payload.llmProvider === "deepseek" || payload.llmProvider === "openai")
      || !Array.isArray(payload.enabledModes)
      || !payload.enabledModes.every(isRolePresentationMode)
      || !isRolePresentationMode(payload.defaultMode)
      || !(payload.defaultSelections === undefined || isRoleDefaultSelections(payload.defaultSelections))
      || typeof payload.memoryEnabled !== "boolean"
      || !(payload.modelId === undefined || payload.modelId === null || typeof payload.modelId === "string")
      || !Array.isArray(payload.toolIds)
      || !payload.toolIds.every((item) => typeof item === "string")
      || !(payload.personaId === null || typeof payload.personaId === "string")
      || !(payload.avatarId === null || typeof payload.avatarId === "string")) {
      return jsonError("角色配置无效", 400);
    }
    const role = await updateRole((await context.params).roleId, {
      displayName: payload.displayName,
      voiceProvider: payload.voiceProvider,
      voiceId: payload.voiceId,
      voiceDialect: isRoleVoiceDialect(payload.voiceDialect) ? payload.voiceDialect : "",
      asrProvider: payload.asrProvider as "doubao" | "dashscope" | null | undefined,
      llmProvider: payload.llmProvider as "deepseek" | "openai" | null | undefined,
      personaId: payload.personaId,
      avatarId: payload.avatarId,
      enabledModes: payload.enabledModes,
      defaultMode: payload.defaultMode,
      defaultSelections: payload.defaultSelections,
      memoryEnabled: payload.memoryEnabled,
      modelId: payload.modelId as string | null | undefined,
      toolIds: payload.toolIds,
    });
    return Response.json({ role }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const message = error instanceof Error ? error.message : "角色保存失败";
    return jsonError(message, message.includes("找不到") ? 404 : /无效|填写/.test(message) ? 400 : 503);
  }
}

export async function DELETE(request: Request, context: Context) {
  if (!authorizeAvatarAssetRequest(request, true)) return jsonError("不允许删除角色", 403);
  try {
    const deleted = await deleteRole((await context.params).roleId);
    return deleted ? Response.json({ deleted: true }) : jsonError("角色不存在", 404);
  } catch (error) {
    const message = error instanceof Error ? error.message : "角色删除失败";
    return jsonError(message, message.includes("不能删除") ? 409 : message.includes("无效") ? 400 : 503);
  }
}

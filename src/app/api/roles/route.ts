import { authorizeAvatarAssetRequest, jsonError } from "@/lib/avatar-assets-server";
import { createRole, listRoles } from "@/lib/role-catalog-repository";
import { isRoleDefaultSelections, isRolePresentationMode, isRoleVoiceDialect } from "@/lib/role-records";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: Request) {
  if (!authorizeAvatarAssetRequest(request, false)) return jsonError("不允许读取角色目录", 403);
  try {
    return Response.json({ roles: await listRoles() }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    console.error("Failed to read role catalog", error);
    return jsonError("角色目录暂时不可用", 503);
  }
}

export async function POST(request: Request) {
  if (!authorizeAvatarAssetRequest(request, true)) return jsonError("不允许创建角色", 403);
  try {
    const payload = await request.json() as Record<string, unknown>;
    if (typeof payload.displayName !== "string"
      || !(payload.personaId === undefined || payload.personaId === null || typeof payload.personaId === "string")
      || !(payload.voiceDialect === undefined || isRoleVoiceDialect(payload.voiceDialect))
      || !(payload.avatarId === undefined || payload.avatarId === null || typeof payload.avatarId === "string")
      || !(payload.enabledModes === undefined || (Array.isArray(payload.enabledModes) && payload.enabledModes.every(isRolePresentationMode)))
      || !(payload.defaultMode === undefined || isRolePresentationMode(payload.defaultMode))
      || !(payload.defaultSelections === undefined || isRoleDefaultSelections(payload.defaultSelections))
      || !(payload.memoryEnabled === undefined || typeof payload.memoryEnabled === "boolean")
      || !(payload.modelId === undefined || payload.modelId === null || typeof payload.modelId === "string")
      || !(payload.toolIds === undefined || (Array.isArray(payload.toolIds) && payload.toolIds.every((item) => typeof item === "string")))) {
      return jsonError("角色配置无效", 400);
    }
    const role = await createRole({
      displayName: payload.displayName,
      voiceProvider: payload.voiceProvider === "doubao" ? "doubao" : "bailian",
      voiceId: typeof payload.voiceId === "string" ? payload.voiceId : undefined,
      voiceDialect: isRoleVoiceDialect(payload.voiceDialect) ? payload.voiceDialect : "",
      personaId: typeof payload.personaId === "string" ? payload.personaId : null,
      avatarId: typeof payload.avatarId === "string" ? payload.avatarId : null,
      enabledModes: Array.isArray(payload.enabledModes) ? payload.enabledModes : undefined,
      defaultMode: isRolePresentationMode(payload.defaultMode) ? payload.defaultMode : undefined,
      defaultSelections: isRoleDefaultSelections(payload.defaultSelections) ? payload.defaultSelections : undefined,
      memoryEnabled: typeof payload.memoryEnabled === "boolean" ? payload.memoryEnabled : undefined,
      modelId: payload.modelId as string | null | undefined,
      toolIds: Array.isArray(payload.toolIds) ? payload.toolIds : undefined,
    });
    return Response.json({ role }, { status: 201, headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const message = error instanceof Error ? error.message : "角色创建失败";
    return jsonError(message, /无效|填写/.test(message) ? 400 : 503);
  }
}

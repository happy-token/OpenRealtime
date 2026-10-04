import { jsonError } from "@/lib/avatar-assets-server";
import { getKnowledgeBindings, setKnowledgeBindings, copyKnowledgeBindings } from "@/lib/knowledge-catalog-repository";
import { requireKnowledgeRole } from "@/lib/knowledge-role-scope";
import { knowledgeOwner } from "@/lib/knowledge-request-auth";
import { getHostedAvatarSettings, saveHostedAvatarSettings } from "@/lib/hosted-avatar-settings-repository";
import { hostedAvatarRoleId } from "@/lib/hosted-avatar-role-id";
import { readLimitedJson, RequestBodyTooLarge } from "@/lib/request-body";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Context = { params: Promise<{ avatarId: string }> };

export async function GET(request: Request, context: Context) {
  try {
    const owner = await knowledgeOwner(request);
    if (owner instanceof Response) return owner;
    const { avatarId } = await context.params;
    const roleId = hostedAvatarRoleId(avatarId);
    const [settings, documentIds] = await Promise.all([getHostedAvatarSettings(owner, avatarId), getKnowledgeBindings(owner, roleId)]);
    return Response.json({ memoryEnabled: settings?.memory_enabled ?? false, documentIds }, { headers: { "Cache-Control": "no-store" } });
  } catch { return jsonError("实时数字人配置读取失败", 503); }
}

export async function PATCH(request: Request, context: Context) {
  try {
    const owner = await knowledgeOwner(request, true);
    if (owner instanceof Response) return owner;
    const { avatarId } = await context.params;
    const roleId = hostedAvatarRoleId(avatarId);
    const payload = await readLimitedJson(request, 4_000) as { memoryEnabled?: unknown; documentIds?: unknown; toolIds?: unknown; sourceRoleId?: unknown };
    if (typeof payload.memoryEnabled !== "boolean" || !Array.isArray(payload.documentIds) || !Array.isArray(payload.toolIds)) return jsonError("配置无效", 400);
    const sourceRoleId = payload.sourceRoleId === undefined ? null : await requireKnowledgeRole(request, payload.sourceRoleId);
    if (sourceRoleId instanceof Response) return sourceRoleId;
    const documentIds = sourceRoleId
      ? await copyKnowledgeBindings(owner, sourceRoleId, roleId, payload.documentIds)
      : await setKnowledgeBindings(owner, roleId, payload.documentIds);
    const settings = await saveHostedAvatarSettings(owner, avatarId, payload.memoryEnabled, payload.toolIds);
    return Response.json({ memoryEnabled: settings.memory_enabled, documentIds }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    if (error instanceof RequestBodyTooLarge) return jsonError("配置过大", 413);
    const message = error instanceof Error ? error.message : "实时数字人配置保存失败";
    return jsonError(message, /无效|不可访问/.test(message) ? 400 : 503);
  }
}

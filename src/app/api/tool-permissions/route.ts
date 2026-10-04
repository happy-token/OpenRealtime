import { conversationOwner } from "@/lib/conversation-history-auth";
import { jsonError } from "@/lib/avatar-assets-server";
import { requireKnowledgeRole } from "@/lib/knowledge-role-scope";
import { getToolPermissions, saveToolPermissions } from "@/lib/tool-permission-repository";
import { isToolPermissionMode } from "@/lib/tool-permission-types";
import { readLimitedJson } from "@/lib/request-body";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const headers = { "Cache-Control": "no-store" };

export async function GET(request: Request) {
  const owner = await conversationOwner(request);
  if (owner instanceof Response) return owner;
  try { return Response.json(await getToolPermissions(owner), { headers }); }
  catch { return jsonError("工具权限配置暂时不可用", 503); }
}

export async function PUT(request: Request) {
  const owner = await conversationOwner(request, true);
  if (owner instanceof Response) return owner;
  try {
    const payload = await readLimitedJson(request, 2000) as { mode?: unknown; roleId?: unknown } | null;
    if (!payload || (!isToolPermissionMode(payload.mode) && payload.mode !== null)
      || !(payload.roleId === undefined || payload.roleId === null || typeof payload.roleId === "string")) return jsonError("工具权限配置无效", 400);
    const roleId = typeof payload.roleId === "string" ? payload.roleId : null;
    if (payload.mode === null && roleId === null) return jsonError("全局权限模式不能为空", 400);
    if (roleId !== null && payload.mode !== null) {
      const role = await requireKnowledgeRole(request, roleId);
      if (role instanceof Response) return role;
    }
    return Response.json(await saveToolPermissions(owner, payload.mode, roleId), { headers });
  } catch (error) {
    const message = error instanceof Error ? error.message : "工具权限保存失败";
    return jsonError(/无效|上限|过大|JSON/.test(message) ? "工具权限配置无效" : "工具权限保存失败", /无效|上限|过大|JSON/.test(message) ? 400 : 503);
  }
}

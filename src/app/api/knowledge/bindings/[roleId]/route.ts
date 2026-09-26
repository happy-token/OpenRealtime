import { jsonError } from "@/lib/avatar-assets-server";
import { getKnowledgeBindings, setKnowledgeBindings } from "@/lib/knowledge-catalog-repository";
import { knowledgeOwner } from "@/lib/knowledge-request-auth";
import { findRole } from "@/lib/role-catalog-repository";
import { findPersonalRole } from "@/lib/personal-role-library";
import { userFromRequest } from "@/lib/user-session";
import { readLimitedJson, RequestBodyTooLarge } from "@/lib/request-body";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Context = { params: Promise<{ roleId: string }> };

export async function GET(request: Request, context: Context) {
  try {
    const owner = await knowledgeOwner(request);
    if (owner instanceof Response) return owner;
    const { roleId } = await context.params;
    if (!await availableRole(request, roleId)) return jsonError("角色不存在", 404);
    return Response.json({ documentIds: await getKnowledgeBindings(owner, roleId) }, { headers: { "Cache-Control": "no-store" } });
  } catch { return jsonError("知识库绑定暂时不可用", 503); }
}

export async function PATCH(request: Request, context: Context) {
  try {
    const owner = await knowledgeOwner(request, true);
    if (owner instanceof Response) return owner;
    const { roleId } = await context.params;
    if (!await availableRole(request, roleId)) return jsonError("角色不存在", 404);
    const payload = await readLimitedJson(request, 2_000) as { documentIds?: unknown };
    if (!Array.isArray(payload?.documentIds)) return jsonError("资料 ID 无效", 400);
    const documentIds = await setKnowledgeBindings(owner, roleId, payload.documentIds);
    return Response.json({ documentIds }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    if (error instanceof RequestBodyTooLarge) return jsonError("请求内容过大", 413);
    const message = error instanceof Error ? error.message : "知识库绑定失败";
    return jsonError(message, /不可访问/.test(message) ? 403 : /无效/.test(message) ? 400 : 503);
  }
}

async function availableRole(request: Request, roleId: string) {
  if (!roleId.startsWith("role-personal-")) return findRole(roleId);
  const user = await userFromRequest(request);
  return user ? findPersonalRole(user, roleId) : null;
}

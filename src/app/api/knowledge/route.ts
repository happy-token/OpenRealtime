import { jsonError } from "@/lib/avatar-assets-server";
import { createKnowledge, listKnowledge, roleKnowledgeBaseId, getKnowledgeBindings } from "@/lib/knowledge-catalog-repository";
import { requireKnowledgeRole, knowledgeError } from "@/lib/knowledge-role-scope";
import { knowledgeOwner } from "@/lib/knowledge-request-auth";
import { readLimitedJson, RequestBodyTooLarge } from "@/lib/request-body";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  try {
    const owner = await knowledgeOwner(request);
    if (owner instanceof Response) return owner;
    const requestedRole = new URL(request.url).searchParams.get("roleId");
    const roleId = requestedRole === null ? undefined : await requireKnowledgeRole(request, requestedRole);
    if (roleId instanceof Response) return roleId;
    const documents = await listKnowledge(owner, undefined, roleId ?? undefined);
    return Response.json({ documents, ...(roleId ? { knowledgeBase: { id: roleKnowledgeBaseId(owner, roleId), roleId },
      documentIds: await getKnowledgeBindings(owner, roleId) } : {}) }, { headers: { "Cache-Control": "no-store" } });
  } catch { return jsonError("知识库暂时不可用", 503); }
}

export async function POST(request: Request) {
  try {
    const owner = await knowledgeOwner(request, true);
    if (owner instanceof Response) return owner;
    const payload = await readLimitedJson(request, 200_000) as { title?: unknown; content?: unknown; roleId?: unknown };
    if (typeof payload?.title !== "string" || typeof payload?.content !== "string") return jsonError("资料内容无效", 400);
    const roleId = payload.roleId == null || payload.roleId === "" ? null : await requireKnowledgeRole(request, payload.roleId);
    if (roleId instanceof Response) return roleId;
    const document = await createKnowledge(owner, payload.title, payload.content, undefined, null, { roleId: roleId ?? undefined });
    return Response.json({ document }, { status: 201, headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    if (error instanceof RequestBodyTooLarge) return jsonError("资料内容过大", 413);
    return knowledgeError(error);
  }
}

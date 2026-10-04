import { jsonError } from "@/lib/avatar-assets-server";
import { updateKnowledge, deleteKnowledge } from "@/lib/knowledge-catalog-repository";
import { knowledgeOwner } from "@/lib/knowledge-request-auth";
import { knowledgeError, requireKnowledgeRole } from "@/lib/knowledge-role-scope";
import { readLimitedJson, RequestBodyTooLarge } from "@/lib/request-body";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Context = { params: Promise<{ documentId: string }> };

async function mutate(request: Request, context: Context, remove: boolean) {
  try {
    const owner = await knowledgeOwner(request, true);
    if (owner instanceof Response) return owner;
    const payload = await readLimitedJson(request, 200_000) as { roleId?: unknown; title?: unknown; content?: unknown; expectedRevision?: unknown };
    if (!payload || typeof payload !== "object") return jsonError("资料内容无效", 400);
    const roleId = payload.roleId == null || payload.roleId === "" ? null : await requireKnowledgeRole(request, payload.roleId);
    if (roleId instanceof Response) return roleId;
    if (!Number.isSafeInteger(payload.expectedRevision) || Number(payload.expectedRevision) < 1) return jsonError("资料版本无效", 400);
    const { documentId } = await context.params;
    if (remove) {
      await deleteKnowledge(owner, roleId, documentId, Number(payload.expectedRevision));
      return Response.json({ deleted: true });
    }
    if (typeof payload.title !== "string" || typeof payload.content !== "string") return jsonError("资料内容无效", 400);
    const document = await updateKnowledge(owner, roleId, documentId, {
      title: payload.title, content: payload.content, expectedRevision: Number(payload.expectedRevision),
    });
    return Response.json({ document });
  } catch (error) {
    return error instanceof RequestBodyTooLarge ? jsonError("资料内容过大", 413) : knowledgeError(error);
  }
}

export async function PATCH(request: Request, context: Context) { return mutate(request, context, false); }
export async function DELETE(request: Request, context: Context) { return mutate(request, context, true); }

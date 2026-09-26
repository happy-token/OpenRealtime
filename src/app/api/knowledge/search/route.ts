import { jsonError } from "@/lib/avatar-assets-server";
import { knowledgePassages, listKnowledge } from "@/lib/knowledge-catalog-repository";
import { knowledgeOwner } from "@/lib/knowledge-request-auth";
import { readLimitedJson, RequestBodyTooLarge } from "@/lib/request-body";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  try {
    const owner = await knowledgeOwner(request, true);
    if (owner instanceof Response) return owner;
    const payload = await readLimitedJson(request, 2_000) as { query?: unknown; documentIds?: unknown };
    if (typeof payload?.query !== "string" || payload.query.length > 500
      || !Array.isArray(payload?.documentIds) || payload.documentIds.length > 30
      || !payload.documentIds.every((id) => typeof id === "string")) return jsonError("检索条件无效", 400);
    const accessible = await listKnowledge(owner);
    const allowed = new Set(accessible.map((doc) => doc.document_id));
    if (payload.documentIds.some((id) => !allowed.has(id))) return jsonError("资料不可访问", 403);
    const selected = new Set(payload.documentIds);
    return Response.json({ passages: knowledgePassages(accessible.filter((doc) => selected.has(doc.document_id)), payload.query) },
      { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return jsonError("检索暂时不可用", error instanceof RequestBodyTooLarge ? 413 : 503);
  }
}

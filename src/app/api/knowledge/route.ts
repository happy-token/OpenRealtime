import { jsonError } from "@/lib/avatar-assets-server";
import { createKnowledge, listKnowledge } from "@/lib/knowledge-catalog-repository";
import { knowledgeOwner } from "@/lib/knowledge-request-auth";
import { readLimitedJson, RequestBodyTooLarge } from "@/lib/request-body";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  try {
    const owner = await knowledgeOwner(request);
    if (owner instanceof Response) return owner;
    return Response.json({ documents: await listKnowledge(owner) }, { headers: { "Cache-Control": "no-store" } });
  } catch { return jsonError("知识库暂时不可用", 503); }
}

export async function POST(request: Request) {
  try {
    const owner = await knowledgeOwner(request, true);
    if (owner instanceof Response) return owner;
    const payload = await readLimitedJson(request, 36_000) as { title?: unknown; content?: unknown };
    if (typeof payload?.title !== "string" || typeof payload?.content !== "string") return jsonError("资料内容无效", 400);
    const document = await createKnowledge(owner, payload.title, payload.content);
    return Response.json({ document }, { status: 201, headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    if (error instanceof RequestBodyTooLarge) return jsonError("资料内容过大", 413);
    const message = error instanceof Error ? error.message : "创建资料失败";
    return jsonError(message, /无效|已存在/.test(message) ? 400 : 503);
  }
}

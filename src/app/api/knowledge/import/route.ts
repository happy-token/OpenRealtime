import { jsonError } from "@/lib/avatar-assets-server";
import { createKnowledge, listKnowledge, updateKnowledge } from "@/lib/knowledge-catalog-repository";
import { requireKnowledgeRole, knowledgeError } from "@/lib/knowledge-role-scope";
import { extractKnowledgeFile, extractKnowledgeUrl } from "@/lib/knowledge-import";
import { knowledgeOwner } from "@/lib/knowledge-request-auth";
import { readLimitedBytes, readLimitedJson, RequestBodyTooLarge } from "@/lib/request-body";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  try {
    const owner = await knowledgeOwner(request, true);
    if (owner instanceof Response) return owner;
    const type = request.headers.get("content-type") ?? "";
    let title: string;
    let content: string;
    let sourceUrl: string | null = null;
    let roleInput: unknown;
    let documentId: unknown;
    let expectedRevision: unknown;
    let sourceKey: string;
    let roleId: string | null | Response;
    async function validateTarget(selectedRole: string | null): Promise<Response | null> {
      if (documentId === undefined || documentId === null) return null;
      if (typeof documentId !== "string" || !Number.isSafeInteger(expectedRevision) || Number(expectedRevision) < 1) return jsonError("资料版本无效", 400);
      const documents = await listKnowledge(owner as string, undefined, selectedRole ?? undefined);
      const existing = documents.find((doc) => doc.document_id === documentId && doc.owner_id === owner);
      if (!existing) return jsonError("资料不可访问", 403);
      if (existing.revision !== expectedRevision) return jsonError("资料版本冲突，请刷新后重试", 409);
      return null;
    }
    if (type.includes("multipart/form-data")) {
      const body = await readLimitedBytes(request, 5_500_000);
      const form = await new Request(request.url, { method: "POST", headers: { "Content-Type": type }, body: new Uint8Array(body).buffer }).formData();
      const file = form.get("file");
      if (!file || typeof file === "string") return jsonError("请选择文件", 400);
      roleInput = form.get("roleId");
      roleId = roleInput == null || roleInput === "" ? null : await requireKnowledgeRole(request, roleInput);
      if (roleId instanceof Response) return roleId;
      documentId = form.get("documentId");
      expectedRevision = form.has("expectedRevision") ? Number(form.get("expectedRevision")) : undefined;
      const denied = await validateTarget(roleId);
      if (denied) return denied;
      title = String(form.get("title") || file.name).trim();
      content = await extractKnowledgeFile(file.name, Buffer.from(await file.arrayBuffer()));
      sourceKey = `file:${file.name.normalize("NFC")}`;
    } else if (type.includes("application/json")) {
      const input = await readLimitedJson(request, 4_000) as { url?: unknown; title?: unknown; roleId?: unknown; documentId?: unknown; expectedRevision?: unknown } | null;
      if (typeof input?.url !== "string") return jsonError("网页地址无效", 400);
      roleInput = input.roleId;
      roleId = roleInput == null || roleInput === "" ? null : await requireKnowledgeRole(request, roleInput);
      if (roleId instanceof Response) return roleId;
      documentId = input.documentId; expectedRevision = input.expectedRevision;
      const denied = await validateTarget(roleId);
      if (denied) return denied;
      const extracted = await extractKnowledgeUrl(input.url);
      title = typeof input.title === "string" && input.title.trim() ? input.title.trim() : extracted.title;
      content = extracted.content;
      sourceUrl = extracted.sourceUrl;
      // Keep the submitted URL stable across redirect changes.
      const source = new URL(input.url); source.hash = "";
      sourceKey = `url:${source.toString()}`;
    } else return jsonError("导入格式无效", 415);
    if (documentId !== undefined && documentId !== null) {
      if (typeof documentId !== "string" || !Number.isSafeInteger(expectedRevision) || Number(expectedRevision) < 1) return jsonError("资料版本无效", 400);
      const document = await updateKnowledge(owner, roleId, documentId, { title, content, sourceUrl, sourceKey, expectedRevision: Number(expectedRevision) });
      return Response.json({ document }, { headers: { "Cache-Control": "no-store" } });
    }
    const document = await createKnowledge(owner, title, content, undefined, sourceUrl, { roleId: roleId ?? undefined, sourceKey });
    return Response.json({ document }, { status: 201, headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    if (error instanceof RequestBodyTooLarge) return jsonError("文件过大", 413);
    return knowledgeError(error);
  }
}

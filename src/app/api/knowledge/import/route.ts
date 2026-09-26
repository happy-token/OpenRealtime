import { jsonError } from "@/lib/avatar-assets-server";
import { createKnowledge } from "@/lib/knowledge-catalog-repository";
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
    if (type.includes("multipart/form-data")) {
      const body = await readLimitedBytes(request, 5_500_000);
      const form = await new Request(request.url, { method: "POST", headers: { "Content-Type": type }, body: new Uint8Array(body).buffer }).formData();
      const file = form.get("file");
      if (!file || typeof file === "string") return jsonError("请选择文件", 400);
      title = String(form.get("title") || file.name).trim();
      content = await extractKnowledgeFile(file.name, Buffer.from(await file.arrayBuffer()));
    } else if (type.includes("application/json")) {
      const input = await readLimitedJson(request, 2_000) as { url?: unknown; title?: unknown } | null;
      if (typeof input?.url !== "string") return jsonError("网页地址无效", 400);
      const extracted = await extractKnowledgeUrl(input.url);
      title = typeof input.title === "string" && input.title.trim() ? input.title.trim() : extracted.title;
      content = extracted.content;
      sourceUrl = extracted.sourceUrl;
    } else return jsonError("导入格式无效", 415);
    const document = await createKnowledge(owner, title, content, undefined, sourceUrl);
    return Response.json({ document }, { status: 201, headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    if (error instanceof RequestBodyTooLarge) return jsonError("文件过大", 413);
    const message = error instanceof Error ? error.message : "资料导入失败";
    return jsonError(message, /无效|支持|过大|过长|仅支持|无法读取|不是文本|没有|非公开|跳转|已存在/.test(message) ? 400 : 503);
  }
}

import { readLimitedJson } from "@/lib/request-body";
import { jsonError } from "@/lib/avatar-assets-server";
import { conversationOwner } from "@/lib/conversation-history-auth";
import { deleteConversation, getConversation, renameConversation } from "@/lib/conversation-history";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Context = { params: Promise<{ conversationId: string }> };

export async function GET(request: Request, context: Context) {
  try {
    const owner = await conversationOwner(request);
    if (owner instanceof Response) return owner;
    const conversation = await getConversation(owner, (await context.params).conversationId);
    return conversation ? Response.json({ conversation }, { headers: { "Cache-Control": "no-store" } }) : jsonError("对话不存在", 404);
  } catch { return jsonError("对话读取失败", 503); }
}

export async function DELETE(request: Request, context: Context) {
  try {
    const owner = await conversationOwner(request, true);
    if (owner instanceof Response) return owner;
    const deleted = await deleteConversation(owner, (await context.params).conversationId);
    return deleted ? Response.json({ deleted: true }) : jsonError("对话不存在", 404);
  } catch { return jsonError("对话删除失败", 503); }
}

export async function PATCH(request: Request, context: Context) {
  try {
    const owner = await conversationOwner(request, true);
    if (owner instanceof Response) return owner;
    const payload = await readLimitedJson(request, 4096).catch(() => null) as { title?: unknown } | null;
    if (!payload || typeof payload.title !== "string" || !payload.title.trim() || payload.title.trim().length > 80 || /[\r\n]/.test(payload.title)) return jsonError("对话名称需为 1–80 个字符，不能换行", 400);
    const conversation = await renameConversation(owner, (await context.params).conversationId, payload.title);
    return conversation ? Response.json({ title: conversation.title }) : jsonError("对话不存在", 404);
  } catch { return jsonError("对话改名失败", 503); }
}

import { jsonError } from "@/lib/avatar-assets-server";
import { conversationOwner } from "@/lib/conversation-history-auth";
import { listConversations, saveConversation } from "@/lib/conversation-history";
import { readLimitedJson, RequestBodyTooLarge } from "@/lib/request-body";
import { addMemory, extractMemories } from "@/lib/memory-catalog";
import { memoryRoleForRequest } from "@/lib/memory-role";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  try {
    const owner = await conversationOwner(request);
    if (owner instanceof Response) return owner;
    return Response.json({ conversations: await listConversations(owner) }, { headers: { "Cache-Control": "no-store" } });
  } catch { return jsonError("对话历史暂时不可用", 503); }
}

export async function POST(request: Request) {
  try {
    const owner = await conversationOwner(request, true);
    if (owner instanceof Response) return owner;
    const input = await readLimitedJson(request, 2_000_000) as Record<string, unknown>;
    const conversation = await saveConversation(owner, {
      id: input.id as string,
      roleId: input.roleId as string | null,
      roleName: input.roleName as string,
      mode: input.mode as string,
      entries: input.entries,
      ended: input.ended as boolean,
    });
    const roleId = conversation.role_id ?? "default-assistant";
    try {
      const role = await memoryRoleForRequest(request, roleId);
      if (role?.memory_enabled) {
        for (const entry of conversation.entries.filter((item) => item.role === "user" && item.isFinal !== false).slice(-5)) {
          for (const candidate of extractMemories(entry.text)) {
            await addMemory(owner, roleId, candidate.kind, candidate.content, conversation.id);
          }
        }
      }
    } catch (error) { console.error("Memory extraction failed", error); }
    return Response.json({ conversation }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    if (error instanceof RequestBodyTooLarge) return jsonError("对话内容过大", 413);
    const message = error instanceof Error ? error.message : "保存对话失败";
    return jsonError(message, /无效|为空|已被使用/.test(message) ? 400 : 503);
  }
}

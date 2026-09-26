import { jsonError } from "@/lib/avatar-assets-server";
import { conversationOwner } from "@/lib/conversation-history-auth";
import { addMemory, listMemories, removeMemory, updateMemory, type MemoryKind } from "@/lib/memory-catalog";
import { memoryRoleForRequest } from "@/lib/memory-role";
import { readLimitedJson, RequestBodyTooLarge } from "@/lib/request-body";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

async function scope(request: Request, mutation = false) {
  const owner = await conversationOwner(request, mutation);
  if (owner instanceof Response) return owner;
  const roleId = new URL(request.url).searchParams.get("roleId") ?? "";
  const role = await memoryRoleForRequest(request, roleId);
  if (!role) return jsonError("角色不存在", 404);
  return { owner, role };
}

export async function GET(request: Request) {
  try {
    const scoped = await scope(request);
    if (scoped instanceof Response) return scoped;
    return Response.json({ memories: await listMemories(scoped.owner, scoped.role.role_id) }, { headers: { "Cache-Control": "no-store" } });
  } catch { return jsonError("记忆读取失败", 503); }
}

export async function POST(request: Request) {
  try {
    const scoped = await scope(request, true);
    if (scoped instanceof Response) return scoped;
    if (!scoped.role.memory_enabled) return jsonError("当前角色已关闭 Memory", 409);
    const input = await readLimitedJson(request, 2_000) as { kind?: MemoryKind; content?: string };
    const memory = await addMemory(scoped.owner, scoped.role.role_id, input.kind as MemoryKind, input.content as string);
    return Response.json({ memory }, { status: 201 });
  } catch (error) { return memoryError(error); }
}

export async function PATCH(request: Request) {
  try {
    const scoped = await scope(request, true);
    if (scoped instanceof Response) return scoped;
    const input = await readLimitedJson(request, 2_000) as { id?: string; content?: string };
    const memory = await updateMemory(scoped.owner, scoped.role.role_id, input.id as string, input.content as string);
    return memory ? Response.json({ memory }) : jsonError("记忆不存在", 404);
  } catch (error) { return memoryError(error); }
}

export async function DELETE(request: Request) {
  try {
    const scoped = await scope(request, true);
    if (scoped instanceof Response) return scoped;
    const id = new URL(request.url).searchParams.get("id");
    await removeMemory(scoped.owner, scoped.role.role_id, id);
    return Response.json({ deleted: true });
  } catch (error) { return memoryError(error); }
}

function memoryError(error: unknown) {
  if (error instanceof RequestBodyTooLarge) return jsonError("记忆内容过大", 413);
  const message = error instanceof Error ? error.message : "记忆操作失败";
  return jsonError(message, /无效|敏感|上限/.test(message) ? 400 : 503);
}

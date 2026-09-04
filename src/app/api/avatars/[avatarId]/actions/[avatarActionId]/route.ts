import { authorizeAvatarAssetRequest, jsonError } from "@/lib/avatar-assets-server";
import { updateOwnedAvatarAction } from "@/lib/avatar-catalog-repository";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function PATCH(
  request: Request,
  context: { params: Promise<{ avatarId: string; avatarActionId: string }> },
) {
  if (!authorizeAvatarAssetRequest(request, true)) return jsonError("不允许修改 Avatar 动作", 403);
  try {
    const { avatarId, avatarActionId } = await context.params;
    const payload = await request.json() as { operation?: unknown; pendingModelCount?: unknown; displayName?: unknown };
    const update = payload.operation === "trash"
      ? { deletedAt: new Date().toISOString() }
      : payload.operation === "restore"
        ? { deletedAt: null }
        : payload.operation === "preparation" && typeof payload.pendingModelCount === "number"
          ? { pendingModelCount: payload.pendingModelCount }
          : payload.operation === "rename" && typeof payload.displayName === "string" && payload.displayName.trim()
            ? { displayName: payload.displayName }
          : null;
    if (!update) return jsonError("Avatar 动作更新操作无效", 400);
    const action = await updateOwnedAvatarAction(avatarId, avatarActionId, update);
    return Response.json({ action }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Avatar 动作更新失败";
    return jsonError(message, message.includes("找不到") ? 404 : message.includes("无效") ? 400 : 503);
  }
}

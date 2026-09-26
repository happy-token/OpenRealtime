import { authorizeAvatarAssetRequest, jsonError } from "@/lib/avatar-assets-server";
import { renameTalkingVariant, setTalkingVariantDeletion } from "@/lib/avatar-catalog-repository";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function PATCH(
  request: Request,
  context: { params: Promise<{ avatarId: string; avatarActionId: string; variantId: string }> },
) {
  if (!authorizeAvatarAssetRequest(request, true)) return jsonError("不允许修改口型对齐", 403);
  try {
    const body: unknown = await request.json();
    if (!body || typeof body !== "object") return jsonError("口型对齐更新操作无效", 400);
    const payload = body as { operation?: unknown; displayName?: unknown };
    const { avatarId, avatarActionId, variantId } = await context.params;
    let action;
    if (payload.operation === "rename") {
      if (typeof payload.displayName !== "string" || !payload.displayName.trim() || payload.displayName.trim().length > 50) {
        return jsonError("口型对齐名称必须为 1–50 字", 400);
      }
      action = await renameTalkingVariant(avatarId, avatarActionId, variantId, payload.displayName.trim());
    } else if (payload.operation === "trash" || payload.operation === "restore") {
      action = await setTalkingVariantDeletion(avatarId, avatarActionId, variantId, payload.operation === "trash");
    } else return jsonError("口型对齐更新操作无效", 400);
    return Response.json({ action }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const message = error instanceof Error ? error.message : "口型对齐更新失败";
    return jsonError(message, message.includes("找不到") ? 404 : message.includes("已有其他") || message.includes("已删除") ? 409 : message.includes("无效") || message.includes("请填写") || message.includes("超过") ? 400 : 503);
  }
}

import { authorizeAvatarAssetRequest, jsonError } from "@/lib/avatar-assets-server";
import { appendOwnedAvatarAction } from "@/lib/avatar-catalog-repository";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function POST(request: Request, context: { params: Promise<{ avatarId: string }> }) {
  if (!authorizeAvatarAssetRequest(request, true)) return jsonError("不允许保存 Avatar 动作", 403);
  try {
    const payload = await request.json() as {
      avatar_action_id?: unknown;
      display_name?: unknown;
      video_url?: unknown;
      pending_model_count?: unknown;
    };
    if (
      typeof payload.avatar_action_id !== "string"
      || typeof payload.display_name !== "string"
      || (payload.video_url !== null && typeof payload.video_url !== "string")
      || (payload.pending_model_count !== undefined && typeof payload.pending_model_count !== "number")
    ) return jsonError("Avatar 动作数据无效", 400);
    const action = await appendOwnedAvatarAction((await context.params).avatarId, {
      avatar_action_id: payload.avatar_action_id,
      display_name: payload.display_name,
      video_url: payload.video_url,
      pending_model_count: payload.pending_model_count,
    });
    return Response.json({ action }, { status: 201, headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Avatar 动作保存失败";
    return jsonError(message, message.includes("找不到") ? 404 : message.includes("无效") || message.includes("填写") ? 400 : 503);
  }
}

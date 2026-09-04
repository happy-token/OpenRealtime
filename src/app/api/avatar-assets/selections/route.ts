import {
  authorizeAvatarAssetRequest,
  avatarAssetControlRequest,
  avatarAssetJsonResponse,
  jsonError,
  validAvatarAssetId,
} from "@/lib/avatar-assets-server";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  if (!authorizeAvatarAssetRequest(request, true)) return jsonError("不允许切换当前动作底片", 403);
  try {
    const payload = await request.json() as { avatarId?: unknown; avatarActionId?: unknown };
    if (!validAvatarAssetId(payload.avatarId) || !validAvatarAssetId(payload.avatarActionId)) {
      return jsonError("avatar_id 或 avatar_action_id 无效", 400);
    }
    const response = await avatarAssetControlRequest("/avatar-assets/selections", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        avatar_id: payload.avatarId,
        avatar_action_id: payload.avatarActionId,
      }),
    });
    return avatarAssetJsonResponse(response, await response.text());
  } catch {
    return jsonError("切换当前动作底片失败", 503);
  }
}

import {
  authorizeAvatarAssetRequest,
  avatarAssetControlRequest,
  avatarAssetJsonResponse,
  jsonError,
  validAvatarAssetId,
} from "@/lib/avatar-assets-server";

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  if (!authorizeAvatarAssetRequest(request, false)) return jsonError("不允许从当前来源读取 Avatar 动作", 403);
  const avatarId = new URL(request.url).searchParams.get("avatarId");
  if (avatarId !== null && !validAvatarAssetId(avatarId)) return jsonError("avatar_id 无效", 400);
  try {
    const query = avatarId ? `?${new URLSearchParams({ avatar_id: avatarId })}` : "";
    const response = await avatarAssetControlRequest(`/avatar-assets/actions${query}`);
    return avatarAssetJsonResponse(response, await response.text());
  } catch {
    return jsonError("Avatar 动作目录暂时不可用", 503);
  }
}

import { authorizeAvatarAssetRequest, jsonError } from "@/lib/avatar-assets-server";
import { createOwnedAvatar, listOwnedAvatars } from "@/lib/avatar-catalog-repository";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: Request) {
  if (!authorizeAvatarAssetRequest(request, false)) return jsonError("不允许读取 Avatar 目录", 403);
  try {
    return Response.json({ avatars: await listOwnedAvatars() }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    console.error("Failed to read Avatar catalog", error);
    return jsonError("Avatar 目录暂时不可用", 503);
  }
}

export async function POST(request: Request) {
  if (!authorizeAvatarAssetRequest(request, true)) return jsonError("不允许创建 Avatar", 403);
  const length = Number(request.headers.get("content-length"));
  if (!Number.isFinite(length) || length <= 0) return jsonError("请求缺少有效的 Content-Length", 411);
  if (length > 6_200_000) return jsonError("Avatar 创建请求过大", 413);
  try {
    const payload = await request.json() as { displayName?: unknown; sourceImageDataUrl?: unknown; avatarId?: unknown };
    if (typeof payload.displayName !== "string" || typeof payload.sourceImageDataUrl !== "string") {
      return jsonError("请提供 Avatar 名称和源图", 400);
    }
    if (payload.avatarId !== undefined && typeof payload.avatarId !== "string") {
      return jsonError("avatar_id 无效", 400);
    }
    const avatar = await createOwnedAvatar({
      displayName: payload.displayName,
      sourceImageDataUrl: payload.sourceImageDataUrl,
      avatarId: payload.avatarId,
    });
    return Response.json({ avatar }, { status: 201, headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Avatar 创建失败";
    return jsonError(message, /无效|格式|超过|已存在|填写|内容/.test(message) ? 400 : 503);
  }
}

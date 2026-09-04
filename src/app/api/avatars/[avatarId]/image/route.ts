import { authorizeAvatarAssetRequest, jsonError } from "@/lib/avatar-assets-server";
import { readOwnedAvatarImage } from "@/lib/avatar-catalog-repository";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: Request, context: { params: Promise<{ avatarId: string }> }) {
  if (!authorizeAvatarAssetRequest(request, false)) return jsonError("不允许读取 Avatar 源图", 403);
  try {
    const image = await readOwnedAvatarImage((await context.params).avatarId);
    if (!image) return jsonError("Avatar 源图不存在", 404);
    return new Response(image.bytes, {
      headers: {
        "Cache-Control": "private, no-store",
        "Content-Type": image.mediaType,
        "Cross-Origin-Resource-Policy": "same-origin",
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Avatar 源图读取失败";
    return jsonError(message, message.includes("无效") ? 400 : 503);
  }
}

import { stat } from "node:fs/promises";
import path from "node:path";
import { authorizeAvatarAssetRequest, jsonError } from "@/lib/avatar-assets-server";
import { attachTalkingVariant } from "@/lib/avatar-catalog-repository";
import type { AvatarTalkingVariant } from "@/lib/avatar-records";

export async function POST(request: Request, context: { params: Promise<{ avatarId: string; avatarActionId: string }> }) {
  if (!authorizeAvatarAssetRequest(request, true)) return jsonError("不允许保存讲话变体", 403);
  try {
    const text = await request.text();
    if (text.length > 4096) return jsonError("参数过大", 400);
    const variant = JSON.parse(text) as AvatarTalkingVariant;
    if (!variant || typeof variant.id !== "string" || !/^[a-z0-9-]{1,100}$/.test(variant.id)) return jsonError("变体 ID 无效", 400);
    const file = await stat(path.join(process.cwd(), "public", "digital-human", "talking-variants", `${variant.id}.mp4`));
    if (!file.isFile()) return jsonError("讲话视频不可用", 400);
    const { avatarId, avatarActionId } = await context.params;
    return Response.json({ action: await attachTalkingVariant(avatarId, avatarActionId, variant) });
  } catch (error) {
    return jsonError(error instanceof Error ? error.message : "保存失败", 400);
  }
}

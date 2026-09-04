import { authorizeAvatarAssetRequest, jsonError } from "@/lib/avatar-assets-server";
import {
  findOwnedAvatar,
  replaceOwnedAvatarSourceImage,
  updateOwnedAvatar,
} from "@/lib/avatar-catalog-repository";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

type Context = { params: Promise<{ avatarId: string }> };
const MAX_PATCH_BODY_BYTES = 6_100_000;

class AvatarPatchRequestError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

export async function GET(request: Request, context: Context) {
  if (!authorizeAvatarAssetRequest(request, false)) return jsonError("不允许读取 Avatar", 403);
  try {
    const avatar = await findOwnedAvatar((await context.params).avatarId);
    return avatar
      ? Response.json({ avatar }, { headers: { "Cache-Control": "no-store" } })
      : jsonError("Avatar 不存在", 404);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Avatar 读取失败";
    return jsonError(message, message.includes("无效") ? 400 : 503);
  }
}

export async function PATCH(request: Request, context: Context) {
  if (!authorizeAvatarAssetRequest(request, true)) return jsonError("不允许修改 Avatar", 403);
  try {
    const { avatarId } = await context.params;
    const payload = await readBoundedJson(request) as {
      operation?: unknown;
      binding?: { provider_avatar_id?: unknown; avatar_model?: unknown; preview_video_url?: unknown };
      sourceImageDataUrl?: unknown;
      trashActions?: unknown;
      displayName?: unknown;
    };
    if (payload.operation === "trash" || payload.operation === "restore") {
      const avatar = await updateOwnedAvatar(avatarId, {
        deletedAt: payload.operation === "trash" ? new Date().toISOString() : null,
      });
      return Response.json({ avatar }, { headers: { "Cache-Control": "no-store" } });
    }
    if (payload.operation === "rename" && typeof payload.displayName === "string" && payload.displayName.trim()) {
      const avatar = await updateOwnedAvatar(avatarId, { displayName: payload.displayName });
      return Response.json({ avatar }, { headers: { "Cache-Control": "no-store" } });
    }
    if (
      payload.operation === "acceptRealtimeBinding"
      && typeof payload.binding?.provider_avatar_id === "string"
      && typeof payload.binding.avatar_model === "string"
      && (payload.binding.preview_video_url == null || typeof payload.binding.preview_video_url === "string")
    ) {
      const avatar = await updateOwnedAvatar(avatarId, {
        realtimeBinding: {
          avatar_id: avatarId,
          provider: "anam",
          provider_avatar_id: payload.binding.provider_avatar_id,
          avatar_model: payload.binding.avatar_model,
          state: "accepted",
          preview_video_url: payload.binding.preview_video_url ?? null,
        },
      });
      return Response.json({ avatar }, { headers: { "Cache-Control": "no-store" } });
    }
    if (
      payload.operation === "replaceSourceImage"
      && typeof payload.sourceImageDataUrl === "string"
      && typeof payload.trashActions === "boolean"
    ) {
      const avatar = await replaceOwnedAvatarSourceImage(avatarId, {
        sourceImageDataUrl: payload.sourceImageDataUrl,
        trashActions: payload.trashActions,
      });
      return Response.json({ avatar }, { headers: { "Cache-Control": "no-store" } });
    }
    return jsonError("Avatar 更新操作无效", 400);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Avatar 更新失败";
    const status = error instanceof AvatarPatchRequestError
      ? error.status
      : error instanceof SyntaxError
        ? 400
        : message.includes("找不到")
          ? 404
          : message.includes("超过") || message.includes("过大")
            ? 413
            : /无效|格式|不匹配|不能为空/.test(message)
              ? 400
              : 503;
    return jsonError(message, status);
  }
}

async function readBoundedJson(request: Request): Promise<unknown> {
  const contentLength = Number(request.headers.get("content-length"));
  if (Number.isFinite(contentLength) && contentLength > MAX_PATCH_BODY_BYTES) {
    throw new AvatarPatchRequestError("Avatar 更新请求体过大", 413);
  }
  if (!request.body) throw new SyntaxError("Avatar 更新请求体不能为空");
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > MAX_PATCH_BODY_BYTES) {
      await reader.cancel();
      throw new AvatarPatchRequestError("Avatar 更新请求体过大", 413);
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return JSON.parse(new TextDecoder().decode(bytes));
}

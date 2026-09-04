import { randomUUID } from "node:crypto";
import {
  authorizeAvatarAssetRequest,
  avatarAssetJsonResponse,
  jsonError,
  persistAvatarCandidate,
  validAvatarAssetId,
} from "@/lib/avatar-assets-server";
import { hasMatchingVideoSignature } from "@/lib/media-signatures";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const VIDEO_TYPES = new Set(["video/mp4", "video/webm", "video/quicktime"]);
const MAX_VIDEO_BYTES = 50 * 1024 * 1024;

export async function POST(request: Request) {
  if (!authorizeAvatarAssetRequest(request, true)) {
    return jsonError("不允许从当前来源创建动作底片候选", 403);
  }
  const length = Number(request.headers.get("content-length"));
  if (!Number.isFinite(length) || length <= 0) return jsonError("请求缺少有效的 Content-Length", 411);
  if (length > MAX_VIDEO_BYTES + 128 * 1024) return jsonError("动作底片不能超过 50MB", 413);
  try {
    const form = await request.formData();
    const video = form.get("video");
    const avatarId = form.get("avatarId");
    const rightsConfirmed = form.get("rightsConfirmed") === "true";
    const idempotencyKey = form.get("idempotencyKey") || randomUUID();
    if (!(video instanceof File) || !VIDEO_TYPES.has(video.type) || !video.size || video.size > MAX_VIDEO_BYTES) {
      return jsonError("仅支持 50MB 内的 MP4、WebM 或 MOV 动作底片", 400);
    }
    if (!validAvatarAssetId(avatarId) || !validAvatarAssetId(idempotencyKey)) {
      return jsonError("Avatar ID 或幂等键无效", 400);
    }
    if (!rightsConfirmed) return jsonError("请先确认素材仅用于当前内部效果测试", 400);
    const bytes = new Uint8Array(await video.arrayBuffer());
    if (!hasMatchingVideoSignature(video.type, bytes)) {
      return jsonError("动作底片内容与文件类型不匹配", 400);
    }
    const response = await persistAvatarCandidate({
      avatarId,
      sourceKind: "upload",
      sourceId: idempotencyKey,
      logicalName: video.name || "motion-base-upload",
      mediaType: video.type,
      idempotencyKey,
      bytes,
    });
    return avatarAssetJsonResponse(response, await response.text());
  } catch (error) {
    console.error("Failed to upload Motion Base Candidate", error);
    return jsonError("动作底片候选服务暂时不可用", 503);
  }
}

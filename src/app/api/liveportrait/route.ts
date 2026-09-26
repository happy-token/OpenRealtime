import { NextRequest, NextResponse } from "next/server";
import { ADMIN_SESSION_COOKIE } from "@/lib/admin-auth";
import { canUseAvatarTestApis, isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import { hasMatchingImageSignature, hasMatchingVideoSignature } from "@/lib/media-signatures";
import {
  createOrReuseLivePortraitTask,
  inspectLivePortraitWorker,
  LivePortraitDrivingValidationError,
  LivePortraitTaskConflictError,
} from "@/lib/liveportrait-worker";
import { validAvatarAssetId } from "@/lib/avatar-assets-server";
import { isLivePortraitActionId } from "@/lib/liveportrait-actions";
import { parseLivePortraitMotionConfig } from "@/lib/liveportrait-motion-config";
import { modelServiceConnection } from "@/lib/model-service-connections";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);
const VIDEO_TYPES = new Set(["video/mp4", "video/webm", "video/quicktime"]);
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
const MAX_VIDEO_BYTES = 50 * 1024 * 1024;

export async function GET(request: NextRequest) {
  if (!canUseAvatarTestApis(request, request.cookies.get(ADMIN_SESSION_COOKIE)?.value)) {
    return json({ error: "不允许从当前来源读取 LivePortrait 状态" }, 403);
  }
  const status = await inspectLivePortraitWorker();
  const connection = await modelServiceConnection("liveportrait");
  return json({
    ready: status.ready,
    device: status.device,
    weights_bytes: status.weightsBytes,
    issues: status.issues,
    templates: status.templates,
    local_only: !connection.url,
  }, status.ready ? 200 : 503);
}

export async function POST(request: NextRequest) {
  if (
    !canUseAvatarTestApis(request, request.cookies.get(ADMIN_SESSION_COOKIE)?.value)
    || !isSameOriginAvatarMutation(request)
  ) {
    return json({ error: "不允许从当前来源创建 LivePortrait 任务" }, 403);
  }
  if (process.env.NODE_ENV === "production") {
    return json({ error: "持久化 LivePortrait Coordinator 尚未部署，生产环境禁止创建任务" }, 503);
  }
  try {
    const length = Number(request.headers.get("content-length"));
    if (!Number.isFinite(length) || length <= 0) return json({ error: "请求缺少有效的 Content-Length" }, 411);
    if (length > MAX_IMAGE_BYTES + MAX_VIDEO_BYTES + 128 * 1024) return json({ error: "请求内容过大" }, 413);
    const form = await request.formData();
    const source = form.get("source");
    const visualIdentityId = form.get("avatarId");
    const driverId = form.get("driverId");
    const driving = form.get("driving");
    const rawLivePortraitConfig = form.get("livePortraitConfig");
    const rightsConfirmed = form.get("rightsConfirmed") === "true";
    if (!(source instanceof File)) return json({ error: "请上传身份源图" }, 400);
    if (!validAvatarAssetId(visualIdentityId)) return json({ error: "avatar_id 无效" }, 400);
    if (!IMAGE_TYPES.has(source.type) || !source.size || source.size > MAX_IMAGE_BYTES) {
      return json({ error: "身份源图仅支持 10MB 内的 PNG、JPEG 或 WebP" }, 400);
    }
    if (!rightsConfirmed) return json({ error: "请先确认身份图和驱动素材的使用权" }, 400);
    let livePortraitConfig;
    try {
      if (typeof rawLivePortraitConfig !== "string") throw new Error("缺少 LivePortrait 动作配置");
      livePortraitConfig = parseLivePortraitMotionConfig(JSON.parse(rawLivePortraitConfig));
    } catch (error) {
      return json({ error: error instanceof Error ? error.message : "LivePortrait 动作配置无效" }, 400);
    }
    const sourceBytes = new Uint8Array(await source.arrayBuffer());
    if (!hasMatchingImageSignature(source.type, sourceBytes)) return json({ error: "身份源图内容与文件类型不匹配" }, 400);

    let drivingBytes: Uint8Array | undefined;
    let drivingExtension: ".mp4" | ".webm" | ".mov" | undefined;
    if (driving instanceof File && driving.size > 0) {
      if (!VIDEO_TYPES.has(driving.type) || driving.size > MAX_VIDEO_BYTES) {
        return json({ error: "Driving Performance 仅支持 50MB 内的 MP4、WebM 或 MOV" }, 400);
      }
      drivingBytes = new Uint8Array(await driving.arrayBuffer());
      if (!hasMatchingVideoSignature(driving.type, drivingBytes)) return json({ error: "Driving Performance 内容与文件类型不匹配" }, 400);
      drivingExtension = driving.type === "video/webm" ? ".webm" : driving.type === "video/quicktime" ? ".mov" : ".mp4";
    } else {
      if (!isLivePortraitActionId(driverId)) return json({ error: "请选择有效的 Driving Performance" }, 400);
    }

    const { task, reused } = await createOrReuseLivePortraitTask({
      sourceBytes,
      sourceExtension: source.type === "image/png" ? ".png" : source.type === "image/webp" ? ".webp" : ".jpg",
      sourceName: source.name,
      visualIdentityId,
      driverId: typeof driverId === "string" ? driverId : "upload",
      drivingBytes,
      drivingExtension,
      livePortraitConfig,
    });
    return json({
      task_id: task.id,
      state: task.state,
      reused,
      driver_id: task.driverId,
      created_at: task.createdAt,
    });
  } catch (error) {
    if (error instanceof LivePortraitDrivingValidationError) {
      return json({ error: error.message }, 400);
    }
    if (error instanceof LivePortraitTaskConflictError) {
      return json({ error: error.message }, 409);
    }
    console.error("Failed to create LivePortrait task", error);
    return json({ error: "LivePortrait 任务创建失败，请检查本地 Worker 日志" }, 500);
  }
}

function json(payload: object, status = 200) {
  return NextResponse.json(payload, { status, headers: { "Cache-Control": "no-store" } });
}

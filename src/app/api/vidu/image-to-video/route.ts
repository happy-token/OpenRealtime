import { createHash } from "node:crypto";
import { NextRequest, NextResponse } from "next/server";
import { ADMIN_SESSION_COOKIE } from "@/lib/admin-auth";
import {
  canUseAvatarTestApis,
  isSameOriginAvatarMutation,
} from "@/lib/avatar-test-access";
import {
  createOrReuseLocalViduTask,
  ViduTaskConflictError,
} from "@/lib/vidu-task-coordinator";
import { createViduImageToVideo, ViduProviderError } from "@/lib/vidu-video";
import { hasMatchingImageSignature } from "@/lib/media-signatures";
import { validAvatarAssetId } from "@/lib/avatar-assets-server";

export const dynamic = "force-dynamic";

const ALLOWED_IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/webp"]);
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;

export async function POST(request: NextRequest) {
  if (
    !canUseAvatarTestApis(request, request.cookies.get(ADMIN_SESSION_COOKIE)?.value)
    || !isSameOriginAvatarMutation(request)
  ) {
    return json({ error: "不允许从当前来源创建 Vidu 任务" }, 403);
  }
  if (process.env.NODE_ENV === "production") {
    return json({ error: "持久化 Avatar Generation Coordinator 尚未部署，生产环境禁止创建付费任务" }, 503);
  }
  try {
    const rawContentLength = request.headers.get("content-length");
    const contentLength = rawContentLength ? Number(rawContentLength) : Number.NaN;
    if (!Number.isFinite(contentLength) || contentLength <= 0) {
      throw new ViduProviderError("请求缺少有效的 Content-Length", 411);
    }
    if (contentLength > MAX_IMAGE_BYTES + 64 * 1024) {
      throw new ViduProviderError("请求内容不能超过 10MB", 413);
    }
    const form = await request.formData();
    const image = form.get("image");
    const prompt = form.get("prompt");
    const visualIdentityId = form.get("avatarId");
    const offPeak = form.get("offPeak") !== "false";
    const creditsAccepted = form.get("creditsAccepted") === "true";
    if (!(image instanceof File)) throw new ViduProviderError("请上传数字人身份图片", 400);
    if (!validAvatarAssetId(visualIdentityId)) {
      throw new ViduProviderError("avatar_id 无效", 400);
    }
    if (!ALLOWED_IMAGE_TYPES.has(image.type)) {
      throw new ViduProviderError("仅支持 PNG、JPEG 或 WebP 图片", 400);
    }
    if (!image.size || image.size > MAX_IMAGE_BYTES) {
      throw new ViduProviderError("图片不能为空且不能超过 10MB", 400);
    }
    const imageBytes = new Uint8Array(await image.arrayBuffer());
    if (!hasMatchingImageSignature(image.type, imageBytes)) {
      throw new ViduProviderError("图片内容与文件类型不匹配", 400);
    }
    if (typeof prompt !== "string") throw new ViduProviderError("请填写动作提示词", 400);
    if (!creditsAccepted) {
      throw new ViduProviderError("请先确认本次生成会消耗 Vidu API credits", 400);
    }
    const imageDataUrl = `data:${image.type};base64,${Buffer.from(imageBytes).toString("base64")}`;
    const { task, reused } = await createOrReuseLocalViduTask(
      {
        visualIdentityId,
        sourceSha256: createHash("sha256").update(imageBytes).digest("hex"),
      },
      () => createViduImageToVideo(
        {
          VIDU_API_KEY: process.env.VIDU_API_KEY,
          VIDU_API_URL: process.env.VIDU_API_URL,
        },
        { imageDataUrl, prompt, offPeak },
      ),
    );
    return json({
      task_id: task.taskId,
      state: task.state,
      model: task.model,
      credits: task.credits,
      off_peak: task.offPeak,
      reused,
    });
  } catch (error) {
    const known = error instanceof ViduProviderError;
    const conflict = error instanceof ViduTaskConflictError;
    return json(
      { error: known || conflict ? error.message : "Vidu 图生视频任务创建失败" },
      known ? error.status : conflict ? 409 : 500,
    );
  }
}

function json(payload: object, status = 200) {
  return NextResponse.json(payload, {
    status,
    headers: { "Cache-Control": "no-store" },
  });
}

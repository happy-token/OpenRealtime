import { mkdir, readFile, rename, stat, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import path from "node:path";
import { currentAdmin } from "@/lib/admin-server";
import { avatarAssetControlRequest } from "@/lib/avatar-assets-server";
import {
  avatarEvaluationPreviewPolicyFromEnv,
  isSameOriginAvatarPreviewRequest,
} from "@/lib/avatar-evaluation-preview";
import {
  type AvatarRendererBinding,
  resolveAvatarRendererBinding,
  resolveBuiltinAvatarSource,
} from "@/lib/avatar-renderer-preparation";
import { resolveAvatarRendererRuntimeForModel } from "@/lib/avatar-renderer-runtime";
import { ensureLiveTalkingProcess } from "@/lib/livetalking-process";
import { hasMatchingImageSignature } from "@/lib/media-signatures";
import { findOwnedAvatar, updateOwnedAvatarAction } from "@/lib/avatar-catalog-repository";
import { isInternalAvatarPresetId } from "@/lib/internal-avatar-ids";
import { DEFAULT_AVATAR_DISPLAY_CONFIG, parseAvatarDisplayConfig } from "@/components/digital-human/types";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const TASK_ID = /^[A-Za-z0-9-]{1,80}$/;
const AVATAR_ID = /^[a-z0-9][a-z0-9_-]{0,63}$/;
const STATIC_IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);
const MAX_STATIC_IMAGE_BYTES = 10 * 1024 * 1024;

type UploadedIdentityImage = {
  bytes: Uint8Array;
  type: string;
};

class PreparationRequestError extends Error {}

export async function POST(request: Request) {
  if (!await authorized(request)) return Response.json({ error: "不允许准备数字人资产" }, { status: 403 });
  try {
    const { displayConfig, sourceImage } = await readPreparationRequest(request);
    const binding = resolveAvatarRendererBinding(displayConfig);
    if (!binding) return Response.json({ error: "当前组合没有可用的本地口型运行时" }, { status: 400 });
    if (sourceImage && binding.avatarActionId !== `builtin:identity-static:${binding.avatarId}`) {
      throw new PreparationRequestError("形象图片只能用于静态 Wav2Lip 准备");
    }
    await assertOwnedAvatarActionIsCurrent(binding);
    const renderer = await readyRenderer(binding.modelId);
    if (!renderer) return Response.json({ error: "Avatar Renderer 未启动" }, { status: 503 });
    if (await rendererPrepared(renderer.internalUrl, binding.rendererAssetId)) {
      await markOwnedAvatarActionPrepared(binding);
      return Response.json({ state: "ready", progress: 100, ...binding });
    }
    const sourcePath = await resolveSourcePath(binding, sourceImage);
    const form = new FormData();
    form.set("model", binding.providerModel);
    form.set("avatar_id", binding.rendererAssetId);
    form.set("img_size", String(binding.modelSize));
    form.set("pads", "0 10 0 0");
    form.set("video_file", new Blob([await readFile(sourcePath)], { type: "video/mp4" }), `${binding.rendererAssetId}.mp4`);
    const response = await fetch(new URL("/api/avatar/task", renderer.internalUrl), {
      method: "POST",
      headers: { "Origin": rendererRequestOrigin() },
      body: form,
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    const payload = await response.json() as { code?: number; msg?: string; data?: { task_id?: string } };
    if (!response.ok || payload.code !== 0 || !payload.data?.task_id) {
      throw new Error(payload.msg || "口型资产准备任务创建失败");
    }
    return Response.json({
      state: "preparing",
      progress: 0,
      taskId: payload.data.task_id,
      ...binding,
    }, { status: 202 });
  } catch (error) {
    if (!(error instanceof PreparationRequestError)) {
      console.error("Failed to prepare avatar renderer asset", error);
    }
    return Response.json(
      { error: error instanceof Error ? error.message : "口型资产准备失败" },
      { status: error instanceof PreparationRequestError ? 400 : 503 },
    );
  }
}

async function assertOwnedAvatarActionIsCurrent(binding: AvatarRendererBinding) {
  if (
    binding.avatarActionId.startsWith("builtin:")
    || (!binding.avatarId.startsWith("avatar-") && !isInternalAvatarPresetId(binding.avatarId))
  ) return;
  const avatar = await findOwnedAvatar(binding.avatarId);
  if (!avatar) return;
  const actionIsCurrent = avatar.actions.some((action) => (
    action.avatar_action_id === binding.avatarActionId && !action.deleted_at
  ));
  if (!actionIsCurrent) {
    throw new PreparationRequestError("已选择动作已删除，请重新选择形象或动作");
  }
}

async function markOwnedAvatarActionPrepared(binding: AvatarRendererBinding) {
  if (binding.avatarActionId.startsWith("builtin:")) return;
  const avatar = await findOwnedAvatar(binding.avatarId);
  const action = avatar?.actions.find((candidate) => (
    candidate.avatar_action_id === binding.avatarActionId && !candidate.deleted_at
  ));
  if (!action || action.pending_model_count === 0) return;
  await updateOwnedAvatarAction(binding.avatarId, binding.avatarActionId, { pendingModelCount: 0 });
}

export async function GET(request: Request) {
  if (!await authorized(request)) return Response.json({ error: "不允许读取数字人准备状态" }, { status: 403 });
  const url = new URL(request.url);
  const taskId = url.searchParams.get("taskId") ?? "";
  const rendererAssetId = url.searchParams.get("rendererAssetId") ?? "";
  if (!AVATAR_ID.test(rendererAssetId) || (taskId && !TASK_ID.test(taskId))) {
    return Response.json({ error: "准备任务参数无效" }, { status: 400 });
  }
  try {
    const binding = preparationStatusBinding(url, rendererAssetId);
    const renderer = await readyRenderer(modelIdFromRendererAssetId(rendererAssetId));
    if (!renderer) return Response.json({ error: "Avatar Renderer 未启动" }, { status: 503 });
    if (!taskId) {
      const ready = await rendererPrepared(renderer.internalUrl, rendererAssetId);
      if (ready && binding) await markOwnedAvatarActionPrepared(binding);
      return Response.json({
        state: ready ? "ready" : "idle",
        progress: ready ? 100 : 0,
        rendererAssetId,
      });
    }
    const response = await fetch(new URL(`/api/avatar/task/${encodeURIComponent(taskId)}`, renderer.internalUrl), {
      headers: { "Origin": rendererRequestOrigin() },
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    const payload = await response.json() as {
      code?: number;
      msg?: string;
      data?: { status?: string; progress?: number; error_msg?: string };
    };
    if (!response.ok || payload.code !== 0 || !payload.data) throw new Error(payload.msg || "准备状态读取失败");
    const providerState = payload.data.status;
    if (providerState === "failed") {
      return Response.json({ state: "failed", progress: payload.data.progress ?? 0, error: payload.data.error_msg || "口型资产准备失败" });
    }
    if (providerState === "completed" && await rendererPrepared(renderer.internalUrl, rendererAssetId)) {
      if (binding) await markOwnedAvatarActionPrepared(binding);
      return Response.json({ state: "ready", progress: 100, rendererAssetId });
    }
    return Response.json({ state: "preparing", progress: payload.data.progress ?? 0, rendererAssetId });
  } catch (error) {
    return Response.json(
      { error: error instanceof Error ? error.message : "准备状态读取失败" },
      { status: error instanceof PreparationRequestError ? 400 : 503 },
    );
  }
}

function preparationStatusBinding(url: URL, rendererAssetId: string) {
  const avatarId = url.searchParams.get("avatarId") ?? "";
  const avatarActionId = url.searchParams.get("avatarActionId") ?? "";
  if (!avatarId && !avatarActionId) return null;
  if (!avatarId || !avatarActionId || avatarId.length > 80 || avatarActionId.length > 160) {
    throw new PreparationRequestError("准备任务绑定参数无效");
  }
  const binding = resolveAvatarRendererBinding({
    ...DEFAULT_AVATAR_DISPLAY_CONFIG,
    renderPath: "segmented",
    segmentedAvatarId: avatarId,
    segmentedAvatarActionId: avatarActionId,
    segmentedLipSyncId: modelIdFromRendererAssetId(rendererAssetId),
  });
  if (!binding || binding.rendererAssetId !== rendererAssetId) {
    throw new PreparationRequestError("准备任务绑定参数无效");
  }
  return binding;
}

async function resolveSourcePath(
  binding: AvatarRendererBinding,
  sourceImage?: UploadedIdentityImage,
) {
  const { avatarId, avatarActionId, rendererAssetId } = binding;
  if (sourceImage) {
    const sourceDirectory = path.join(process.cwd(), "data", "avatar-renderer", "sources");
    await mkdir(sourceDirectory, { recursive: true });
    const extension = sourceImage.type === "image/png" ? "png" : sourceImage.type === "image/webp" ? "webp" : "jpg";
    const destination = path.join(sourceDirectory, `${rendererAssetId}-identity.${extension}`);
    const temporary = `${destination}.${crypto.randomUUID()}.tmp`;
    await writeFile(temporary, sourceImage.bytes);
    await rename(temporary, destination);
    return createStaticMotionSource(destination, rendererAssetId);
  }
  const builtin = resolveBuiltinAvatarSource(binding);
  if (builtin) {
    const absolute = path.join(process.cwd(), builtin);
    await stat(absolute);
    if (!/\.(png|jpe?g|webp)$/i.test(absolute)) return absolute;
    return createStaticMotionSource(absolute, rendererAssetId);
  }

  const catalogResponse = await avatarAssetControlRequest(
    `/avatar-assets/actions?${new URLSearchParams({ avatar_id: avatarId })}`,
  );
  const catalog = await catalogResponse.json() as {
    actions?: Array<{ avatar_action_id?: string; source_master_artifact_id?: string }>;
  };
  const motion = catalog.actions?.find((candidate) => candidate.avatar_action_id === avatarActionId);
  if (!catalogResponse.ok || !motion?.source_master_artifact_id) {
    throw new Error("已选择动作底片不可用于口型预处理");
  }
  const artifactResponse = await avatarAssetControlRequest(
    `/avatar-assets/artifacts/${encodeURIComponent(motion.source_master_artifact_id)}`,
    {},
    60_000,
  );
  if (!artifactResponse.ok) throw new Error("动作底片文件读取失败");
  const sourceDirectory = path.join(process.cwd(), "data", "avatar-renderer", "sources");
  await mkdir(sourceDirectory, { recursive: true });
  const destination = path.join(sourceDirectory, `${rendererAssetId}.mp4`);
  const temporary = `${destination}.${crypto.randomUUID()}.tmp`;
  await writeFile(temporary, new Uint8Array(await artifactResponse.arrayBuffer()));
  await rename(temporary, destination);
  return destination;
}

async function readyRenderer(modelId: AvatarRendererBinding["modelId"]) {
  const renderer = resolveAvatarRendererRuntimeForModel(modelId);
  if (renderer?.mode === "managed") {
    await ensureLiveTalkingProcess(process.cwd(), renderer.port, renderer.modelSize);
  }
  return renderer;
}

function modelIdFromRendererAssetId(
  rendererAssetId: string,
): AvatarRendererBinding["modelId"] {
  return rendererAssetId === "shuchang" || rendererAssetId.startsWith("wav2lip96-")
    ? "wav2lip96"
    : "wav2lip256";
}

async function readPreparationRequest(request: Request) {
  const contentType = request.headers.get("content-type") ?? "";
  if (!contentType.toLowerCase().startsWith("multipart/form-data")) {
    return {
      displayConfig: parseAvatarDisplayConfig(await request.json()),
      sourceImage: undefined,
    };
  }

  const form = await request.formData();
  const config = form.get("config");
  if (typeof config !== "string" || config.length > 32_000) {
    throw new PreparationRequestError("数字人准备配置无效");
  }
  let configPayload: unknown;
  try {
    configPayload = JSON.parse(config);
  } catch {
    throw new PreparationRequestError("数字人准备配置无效");
  }
  const image = form.get("source_image");
  if (!(image instanceof Blob)) {
    throw new PreparationRequestError("缺少形象图片");
  }
  if (!STATIC_IMAGE_TYPES.has(image.type)) {
    throw new PreparationRequestError("仅支持 JPEG、PNG 或 WebP 形象图片");
  }
  if (image.size <= 0 || image.size > MAX_STATIC_IMAGE_BYTES) {
    throw new PreparationRequestError("形象图片不能超过 10MB");
  }
  const bytes = new Uint8Array(await image.arrayBuffer());
  if (!hasMatchingImageSignature(image.type, bytes)) {
    throw new PreparationRequestError("形象图片内容与文件格式不匹配");
  }
  return {
    displayConfig: parseAvatarDisplayConfig(configPayload),
    sourceImage: { bytes, type: image.type },
  };
}

async function createStaticMotionSource(imagePath: string, avatarId: string) {
  const sourceDirectory = path.join(process.cwd(), "data", "avatar-renderer", "sources");
  await mkdir(sourceDirectory, { recursive: true });
  const destination = path.join(sourceDirectory, `${avatarId}.mp4`);
  try {
    await stat(destination);
    return destination;
  } catch {
    // The immutable binding has not been materialized yet.
  }
  const temporary = `${destination}.${crypto.randomUUID()}.tmp.mp4`;
  await new Promise<void>((resolve, reject) => {
    const process = spawn("ffmpeg", [
      "-hide_banner", "-loglevel", "error", "-y",
      "-loop", "1", "-i", imagePath,
      "-t", "4", "-r", "25", "-an",
      "-c:v", "libx264", "-pix_fmt", "yuv420p", temporary,
    ], { stdio: ["ignore", "ignore", "pipe"] });
    let stderr = "";
    const timeout = setTimeout(() => process.kill("SIGTERM"), 60_000);
    process.stderr.on("data", (chunk) => { stderr += String(chunk).slice(0, 2_000); });
    process.once("error", reject);
    process.once("exit", (code) => {
      clearTimeout(timeout);
      if (code === 0) resolve();
      else reject(new Error(stderr.trim() || `静态动作底片生成失败（${code ?? "terminated"}）`));
    });
  });
  await rename(temporary, destination);
  return destination;
}

async function rendererPrepared(internalUrl: string, avatarId: string) {
  const response = await fetch(new URL(`/api/avatar/prepared/${encodeURIComponent(avatarId)}`, internalUrl), {
    headers: { "Origin": rendererRequestOrigin() },
    cache: "no-store",
    signal: AbortSignal.timeout(10_000),
  });
  if (!response.ok) return false;
  const payload = await response.json() as { code?: number; data?: { state?: string; avatar_id?: string } };
  return payload.code === 0 && payload.data?.state === "ready" && payload.data.avatar_id === avatarId;
}

async function authorized(request: Request): Promise<boolean> {
  const policy = avatarEvaluationPreviewPolicyFromEnv();
  if (!policy.enabled) return false;
  if (policy.localDevelopmentAccess && isSameOriginAvatarPreviewRequest(request)) return true;
  return Boolean(await currentAdmin());
}

function rendererRequestOrigin() {
  const value = process.env.OPENREALTIME_AVATAR_RENDERER_REQUEST_ORIGIN ?? "http://127.0.0.1:3010";
  const url = new URL(value);
  if (!/^https?:$/.test(url.protocol) || url.pathname !== "/" || url.search || url.hash) {
    throw new Error("OPENREALTIME_AVATAR_RENDERER_REQUEST_ORIGIN must be an HTTP(S) origin");
  }
  return url.origin;
}

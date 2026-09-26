import { execFile } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdir, mkdtemp, readFile, rename, rm, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";
import { NextRequest } from "next/server";
import {
  ADMIN_SESSION_COOKIE,
  adminAuthConfigFromEnv,
  verifyAdminSessionToken,
} from "@/lib/admin-auth";
import { isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import {
  deleteBailianClonedVoice,
  isValidBailianVoiceId,
  listBailianClonedVoices,
  voiceCloneConfiguration,
} from "@/lib/bailian-voice-clones";
import { hasMatchingAudioSignature } from "@/lib/media-signatures";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const MAX_AUDIO_BYTES = 10 * 1024 * 1024;
const ALLOWED_AUDIO_TYPES = new Set([
  "audio/wav",
  "audio/x-wav",
  "audio/mpeg",
  "audio/mp4",
  "audio/x-m4a",
  "audio/webm",
  "audio/ogg",
]);
const TYPE_SUFFIX: Record<string, string> = {
  "audio/wav": ".wav",
  "audio/x-wav": ".wav",
  "audio/mpeg": ".mp3",
  "audio/mp4": ".m4a",
  "audio/x-m4a": ".m4a",
  "audio/webm": ".webm",
  "audio/ogg": ".ogg",
};
const LABEL_PATTERN = /^.{1,32}$/u;
const AUDIO_SUFFIXES = new Set([".wav", ".mp3", ".m4a", ".webm", ".ogg"]);
const ENROLLMENT_LIMIT = 3;
const ENROLLMENT_WINDOW_MS = 10 * 60 * 1000;
const execFileAsync = promisify(execFile);
const catalogDirectory = join(process.cwd(), "tmp", "voice-clones");
const catalogPath = join(catalogDirectory, "catalog.json");
const enrollmentAttempts = new Map<string, number[]>();

export async function GET(request: NextRequest) {
  if (!authorizeVoiceCloneMutation(request)) {
    return json({ error: "不允许从当前来源读取克隆音色" }, 403);
  }
  const configuration = voiceCloneConfiguration();
  const labels = await readLabels();
  try {
    const voices = await listBailianClonedVoices(labels);
    const configuredActiveVoiceId = process.env.BAILIAN_TTS_VOICE?.trim() || null;
    return json({
      provider: "bailian",
      ...configuration,
      activeVoiceId: configuredActiveVoiceId && voices.some((voice) => voice.id === configuredActiveVoiceId)
        ? configuredActiveVoiceId
        : null,
      voices,
    });
  } catch (error) {
    return json({
      provider: "bailian",
      ...configuration,
      voices: [],
      error: error instanceof Error ? localizeProviderError(error.message) : "克隆音色目录暂不可用",
    });
  }
}

export async function POST(request: NextRequest) {
  if (!authorizeVoiceCloneMutation(request)) {
    return json({ error: "不允许从当前来源创建克隆音色" }, 403);
  }
  if (!consumeEnrollmentAttempt(request)) {
    return json({ error: "克隆请求过于频繁，请十分钟后再试" }, 429);
  }
  const contentLength = Number(request.headers.get("content-length"));
  if (!Number.isFinite(contentLength) || contentLength <= 0) {
    return json({ error: "请求缺少有效的 Content-Length" }, 411);
  }
  if (contentLength > MAX_AUDIO_BYTES + 128 * 1024) {
    return json({ error: "克隆音频不能超过 10MB" }, 413);
  }
  const configuration = voiceCloneConfiguration();
  if (!configuration.configured) {
    return json({ error: `克隆服务尚未完成服务端配置：${configuration.missing.join(", ")}` }, 503);
  }

  let workingDirectory = "";
  try {
    const form = await request.formData();
    const displayName = form.get("displayName");
    const audio = form.get("audio");
    const sourceKind = form.get("sourceKind");
    if (typeof displayName !== "string" || !LABEL_PATTERN.test(displayName.trim())) {
      return json({ error: "请填写 1–32 个字符的音色名称" }, 400);
    }
    if (sourceKind !== "recording" && sourceKind !== "upload") {
      return json({ error: "音频来源无效" }, 400);
    }
    if (form.get("rightsConfirmed") !== "true") {
      return json({ error: "请确认已获得该声音的克隆与使用授权" }, 400);
    }
    if (!(audio instanceof File) || !audio.size || audio.size > MAX_AUDIO_BYTES) {
      return json({ error: "请选择 10MB 内的音频文件" }, 400);
    }
    const mediaType = audio.type.toLowerCase().split(";", 1)[0];
    const suffix = audio.name.toLowerCase().match(/\.[^.]+$/)?.[0];
    if (!ALLOWED_AUDIO_TYPES.has(mediaType) || !suffix || !AUDIO_SUFFIXES.has(suffix)) {
      return json({ error: "仅支持 WAV、MP3、M4A、WebM 或 OGG 音频" }, 400);
    }
    const bytes = new Uint8Array(await audio.arrayBuffer());
    if (!hasMatchingAudioSignature(mediaType, bytes)) {
      return json({ error: "音频内容与文件类型不匹配" }, 400);
    }

    workingDirectory = await mkdtemp(join(tmpdir(), "openrealtime-voice-clone-"));
    const inputPath = join(workingDirectory, `source${TYPE_SUFFIX[mediaType]}`);
    const preparedPath = join(workingDirectory, "prepared.wav");
    await writeFile(inputPath, bytes);
    const python = resolvePythonBinary();
    await execFileAsync(python, [
      join(process.cwd(), "scripts", "prepare_voice_clone_sample.py"),
      inputPath,
      preparedPath,
      "--duration",
      "20",
      "--force",
      "--rights-confirmed",
    ], { timeout: 90_000, maxBuffer: 1024 * 1024 });
    const enrollment = await execFileAsync(python, [
      join(process.cwd(), "scripts", "enroll_bailian_voice_clone.py"),
      preparedPath,
      "--prefix",
      "openrt",
      "--rights-confirmed",
    ], { timeout: 120_000, maxBuffer: 1024 * 1024 });
    const result = JSON.parse(enrollment.stdout.trim()) as {
      voice_id?: unknown;
      target_model?: unknown;
      request_id?: unknown;
    };
    if (typeof result.voice_id !== "string") throw new Error("克隆服务未返回音色 ID");
    await saveLabel(result.voice_id, displayName.trim());
    return json({
      voice: {
        id: result.voice_id,
        displayName: displayName.trim(),
        status: "OK",
        createdAt: new Date().toISOString(),
      },
      targetModel: typeof result.target_model === "string" ? result.target_model : configuration.targetModel,
      requestId: typeof result.request_id === "string" ? result.request_id : null,
    }, 201);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    console.error("Failed to create Bailian cloned voice", detail);
    return json({ error: localizeProviderError(detail) }, 502);
  } finally {
    if (workingDirectory) await rm(workingDirectory, { recursive: true, force: true }).catch(() => undefined);
  }
}

export async function PATCH(request: NextRequest) {
  if (!authorizeVoiceCloneMutation(request)) {
    return json({ error: "不允许从当前来源修改克隆音色" }, 403);
  }
  const body = await readManagementBody(request);
  if (!body) return json({ error: "音色管理请求无效" }, 400);
  if (!isValidBailianVoiceId(body.voiceId)) return json({ error: "音色 ID 无效" }, 400);
  if (typeof body.displayName !== "string" || !LABEL_PATTERN.test(body.displayName.trim())) {
    return json({ error: "请填写 1–32 个字符的音色名称" }, 400);
  }
  try {
    await saveLabel(body.voiceId, body.displayName.trim());
    return json({ voice: { id: body.voiceId, displayName: body.displayName.trim() } });
  } catch (error) {
    console.error("Failed to rename Bailian cloned voice", error);
    return json({ error: "音色名称保存失败，请稍后重试" }, 500);
  }
}

export async function DELETE(request: NextRequest) {
  if (!authorizeVoiceCloneMutation(request)) {
    return json({ error: "不允许从当前来源删除克隆音色" }, 403);
  }
  const body = await readManagementBody(request);
  if (!body || !isValidBailianVoiceId(body.voiceId)) return json({ error: "音色 ID 无效" }, 400);
  try {
    await deleteBailianClonedVoice(body.voiceId);
    await removeLabel(body.voiceId);
    return json({ deleted: true, voiceId: body.voiceId });
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    console.error("Failed to delete Bailian cloned voice", detail);
    return json({ error: localizeProviderError(detail, "delete") }, 502);
  }
}

function resolvePythonBinary() {
  const configured = process.env.VOICEAGENT_PYTHON_BIN?.trim();
  if (configured) return configured;
  const virtualEnvironmentPython = join(process.cwd(), ".venv", "bin", "python");
  return existsSync(virtualEnvironmentPython) ? virtualEnvironmentPython : "python3";
}

async function readLabels(): Promise<Record<string, string>> {
  try {
    const parsed = JSON.parse(await readFile(catalogPath, "utf8"));
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    return Object.fromEntries(Object.entries(parsed).filter((entry): entry is [string, string] => (
      typeof entry[0] === "string" && typeof entry[1] === "string"
    )));
  } catch {
    return {};
  }
}

async function saveLabel(voiceId: string, displayName: string) {
  const labels = await readLabels();
  await writeLabels({ ...labels, [voiceId]: displayName });
}

async function removeLabel(voiceId: string) {
  const labels = await readLabels();
  if (!(voiceId in labels)) return;
  delete labels[voiceId];
  await writeLabels(labels);
}

async function writeLabels(labels: Record<string, string>) {
  await mkdir(catalogDirectory, { recursive: true });
  const temporaryPath = join(catalogDirectory, `${randomUUID()}.json`);
  await writeFile(temporaryPath, JSON.stringify(labels, null, 2));
  await rename(temporaryPath, catalogPath);
}

async function readManagementBody(request: NextRequest) {
  const contentLength = Number(request.headers.get("content-length"));
  if (!Number.isFinite(contentLength) || contentLength <= 0 || contentLength > 4096) return null;
  try {
    const body = await request.json() as { voiceId?: unknown; displayName?: unknown };
    return typeof body.voiceId === "string" ? { voiceId: body.voiceId, displayName: body.displayName } : null;
  } catch {
    return null;
  }
}

function localizeProviderError(message: string, operation: "create" | "delete" = "create") {
  if (/at least 5 seconds|prepared audio/i.test(message)) return "音频至少需要包含 5 秒连续清晰语音，建议录制 10–20 秒";
  if (/missing required environment variable/i.test(message)) return "克隆服务的服务端存储或百炼凭据尚未配置完整";
  if (/Bailian voice enrollment failed/i.test(message)) return "百炼未能创建克隆音色，请检查样本质量、模型与业务空间配置";
  if (/timed out|timeout/i.test(message)) return "克隆请求超时，请稍后重试";
  if (operation === "delete") return "删除克隆音色失败，请检查百炼服务状态";
  if (/音色 ID|voice_id/i.test(message)) return "百炼克隆服务未返回可用音色，请稍后重试";
  return "克隆音色创建失败，请检查服务端日志";
}

function authorizeVoiceCloneMutation(request: NextRequest) {
  if (!isSameOriginAvatarMutation(request)) return false;
  const hostname = request.nextUrl.hostname;
  if (process.env.NODE_ENV !== "production" && ["localhost", "127.0.0.1", "[::1]"].includes(hostname)) {
    return true;
  }
  const adminConfig = adminAuthConfigFromEnv();
  return Boolean(adminConfig && verifyAdminSessionToken(
    request.cookies.get(ADMIN_SESSION_COOKIE)?.value,
    adminConfig,
  ));
}

function consumeEnrollmentAttempt(request: NextRequest) {
  const now = Date.now();
  const key = request.headers.get("x-forwarded-for")?.split(",", 1)[0].trim()
    || request.headers.get("x-real-ip")?.trim()
    || request.nextUrl.hostname;
  const recent = (enrollmentAttempts.get(key) || []).filter((timestamp) => now - timestamp < ENROLLMENT_WINDOW_MS);
  if (recent.length >= ENROLLMENT_LIMIT) return false;
  enrollmentAttempts.set(key, [...recent, now]);
  if (enrollmentAttempts.size > 500) {
    for (const [candidate, timestamps] of enrollmentAttempts) {
      if (!timestamps.some((timestamp) => now - timestamp < ENROLLMENT_WINDOW_MS)) enrollmentAttempts.delete(candidate);
    }
  }
  return true;
}

function json(payload: object, status = 200) {
  return Response.json(payload, {
    status,
    headers: {
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

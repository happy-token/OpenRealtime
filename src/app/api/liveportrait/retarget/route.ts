import { execFile } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { NextRequest, NextResponse } from "next/server";
import { ADMIN_SESSION_COOKIE } from "@/lib/admin-auth";
import { canUseAvatarTestApis, isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import { hasMatchingImageSignature } from "@/lib/media-signatures";
import { inspectLivePortraitWorker } from "@/lib/liveportrait-worker";
import { parseLivePortraitRetargetConfig } from "@/lib/liveportrait-retarget-config";
import { modelServiceConnection } from "@/lib/model-service-connections";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const maxDuration = 900;

const execFileAsync = promisify(execFile);
const IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;

export async function POST(request: NextRequest) {
  if (
    !canUseAvatarTestApis(request, request.cookies.get(ADMIN_SESSION_COOKIE)?.value)
    || !isSameOriginAvatarMutation(request)
  ) {
    return NextResponse.json({ error: "不允许从当前来源创建 LivePortrait 姿态预览" }, { status: 403 });
  }
  const connection = await modelServiceConnection("liveportrait");
  if (process.env.NODE_ENV === "production" && !connection.url) {
    return NextResponse.json({ error: "LivePortrait 姿态预览仅在本地工作台可用" }, { status: 503 });
  }

  let temporaryDirectory = "";
  try {
    const length = Number(request.headers.get("content-length"));
    if (!Number.isFinite(length) || length <= 0) {
      return NextResponse.json({ error: "请求缺少有效的 Content-Length" }, { status: 411 });
    }
    if (length > MAX_IMAGE_BYTES + 64 * 1024) {
      return NextResponse.json({ error: "请求内容过大" }, { status: 413 });
    }

    const form = await request.formData();
    const source = form.get("source");
    const rawConfig = form.get("retargetConfig");
    const rightsConfirmed = form.get("rightsConfirmed") === "true";
    if (!(source instanceof File)) return NextResponse.json({ error: "请上传身份源图" }, { status: 400 });
    if (!IMAGE_TYPES.has(source.type) || !source.size || source.size > MAX_IMAGE_BYTES) {
      return NextResponse.json({ error: "身份源图仅支持 10MB 内的 PNG、JPEG 或 WebP" }, { status: 400 });
    }
    if (!rightsConfirmed) return NextResponse.json({ error: "请先确认身份图的使用权" }, { status: 400 });
    if (typeof rawConfig !== "string") return NextResponse.json({ error: "缺少 LivePortrait 姿态配置" }, { status: 400 });
    let retargetConfig;
    try {
      retargetConfig = parseLivePortraitRetargetConfig(JSON.parse(rawConfig));
    } catch (error) {
      return NextResponse.json({ error: error instanceof Error ? error.message : "LivePortrait 姿态配置无效" }, { status: 400 });
    }
    const sourceBytes = new Uint8Array(await source.arrayBuffer());
    if (!hasMatchingImageSignature(source.type, sourceBytes)) {
      return NextResponse.json({ error: "身份源图内容与文件类型不匹配" }, { status: 400 });
    }

    const status = await inspectLivePortraitWorker();
    if (!status.ready) return NextResponse.json({ error: status.issues[0] || "LivePortrait Runtime 尚未就绪" }, { status: 503 });

    if (connection.url) {
      const extension = source.type === "image/png" ? ".png" : source.type === "image/webp" ? ".webp" : ".jpg";
      const remoteForm = new FormData();
      remoteForm.set("source_image", new Blob([sourceBytes], { type: source.type }), `source${extension}`);
      remoteForm.set("config_json", JSON.stringify(retargetConfig));
      remoteForm.set("rights_confirmed", "true");
      const remote = await fetch(`${connection.url}/v1/retarget`, {
        method: "POST", headers: connection.token ? { Authorization: `Bearer ${connection.token}` } : undefined,
        body: remoteForm, cache: "no-store", signal: AbortSignal.timeout(900_000),
      });
      if (!remote.ok) return NextResponse.json({ error: `LivePortrait 远端姿态预览失败（HTTP ${remote.status}）` }, { status: 502 });
      return new NextResponse(await remote.arrayBuffer(), {
        status: 200, headers: { "Cache-Control": "no-store", "Content-Type": "image/png" },
      });
    }

    temporaryDirectory = await mkdtemp(path.join(os.tmpdir(), "openrealtime-retarget-"));
    const extension = source.type === "image/png" ? ".png" : source.type === "image/webp" ? ".webp" : ".jpg";
    const sourcePath = path.join(temporaryDirectory, `source${extension}`);
    const configPath = path.join(temporaryDirectory, "retarget-config.json");
    const outputPath = path.join(temporaryDirectory, "preview.png");
    await writeFile(sourcePath, sourceBytes, { flag: "wx", mode: 0o600 });
    await writeFile(configPath, JSON.stringify(retargetConfig), { flag: "wx", mode: 0o600 });

    const projectRoot = process.cwd();
    const runtimeRoot = process.env.LIVEPORTRAIT_RUNTIME_ROOT ?? path.join(projectRoot, "models/liveportrait");
    const runtimePython = path.join(runtimeRoot, ".venv/bin/python");
    await execFileAsync(runtimePython, [
      path.join(projectRoot, "scripts/liveportrait_retarget_image.py"),
      sourcePath,
      outputPath,
      configPath,
      "--repository",
      path.join(runtimeRoot, "repository"),
    ], {
      cwd: projectRoot,
      timeout: 900_000,
      maxBuffer: 512 * 1024,
      env: { ...process.env, PYTORCH_ENABLE_MPS_FALLBACK: "1" },
    });
    const result = await readFile(outputPath);
    return new NextResponse(result, {
      status: 200,
      headers: { "Cache-Control": "no-store", "Content-Type": "image/png" },
    });
  } catch (error) {
    console.error("Failed to create LivePortrait pose preview", error);
    const message = error instanceof Error && error.message.includes("NO face detected")
      ? "身份源图中没有检测到清晰人脸"
      : "LivePortrait 姿态预览生成失败，请检查本地 Runtime 日志";
    return NextResponse.json({ error: message }, { status: 500 });
  } finally {
    if (temporaryDirectory) await rm(temporaryDirectory, { recursive: true, force: true });
  }
}

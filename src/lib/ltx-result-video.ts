import { hasMatchingVideoSignature } from "./media-signatures";
import { assertSafeLtxResultUrl } from "./ltx-result-url";

const MAX_VIDEO_BYTES = 50 * 1024 * 1024;

export async function downloadLtxResultVideo(value: string, fetcher: typeof fetch = fetch) {
  const safeUrl = await assertSafeLtxResultUrl(value);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30_000);
  try {
    const response = await fetcher(safeUrl, {
      cache: "no-store",
      redirect: "error",
      signal: controller.signal,
    });
    if (!response.ok || !response.body) throw new Error("视频生成结果下载失败");
    const bytes = await readBoundedBody(response);
    return {
      bytes,
      mediaType: identifyVideoType(response.headers.get("content-type"), bytes),
    };
  } finally {
    clearTimeout(timeout);
  }
}

async function readBoundedBody(response: Response) {
  const declaredLength = Number(response.headers.get("content-length"));
  if (Number.isFinite(declaredLength) && declaredLength > MAX_VIDEO_BYTES) {
    throw new Error("视频生成结果超过 50MB");
  }
  const reader = response.body!.getReader();
  const chunks: Uint8Array[] = [];
  let length = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    length += value.byteLength;
    if (length > MAX_VIDEO_BYTES) {
      await reader.cancel();
      throw new Error("视频生成结果超过 50MB");
    }
    chunks.push(value);
  }
  if (!length) throw new Error("视频生成服务返回了空视频");
  const result = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    result.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return result;
}

function identifyVideoType(header: string | null, bytes: Uint8Array) {
  const candidate = header?.split(";", 1)[0].trim().toLowerCase();
  for (const mediaType of [candidate, "video/mp4", "video/webm", "video/quicktime"]) {
    if (mediaType && hasMatchingVideoSignature(mediaType, bytes)) return mediaType;
  }
  throw new Error("视频生成结果不是支持的视频容器");
}

import {
  authorizeAvatarAssetRequest,
  avatarAssetControlRequest,
  jsonError,
  validAvatarAssetId,
} from "@/lib/avatar-assets-server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(
  request: Request,
  context: { params: Promise<{ artifactId: string }> },
) {
  if (!authorizeAvatarAssetRequest(request, false)) return jsonError("不允许预览当前资产", 403);
  const { artifactId } = await context.params;
  if (!validAvatarAssetId(artifactId)) return jsonError("Artifact ID 无效", 400);
  try {
    const range = request.headers.get("range");
    const response = await avatarAssetControlRequest(
      `/avatar-assets/artifacts/${encodeURIComponent(artifactId)}`,
      range ? { headers: { Range: range } } : {},
      60_000,
    );
    const contentType = response.headers.get("content-type") ?? "application/octet-stream";
    if (!response.ok && response.status !== 416) {
      return new Response(await response.text(), {
        status: response.status,
        headers: { "Content-Type": "application/json; charset=utf-8" },
      });
    }
    const headers = new Headers({
      "Accept-Ranges": response.headers.get("accept-ranges") ?? "bytes",
      "Cache-Control": response.headers.get("cache-control") ?? "private, max-age=3600, immutable",
      "Content-Type": contentType,
      "Cross-Origin-Resource-Policy": "same-origin",
      "X-Content-Type-Options": "nosniff",
    });
    for (const name of ["content-length", "content-range"]) {
      const value = response.headers.get(name);
      if (value) headers.set(name, value);
    }
    return new Response(response.body, {
      status: response.status,
      headers,
    });
  } catch {
    return jsonError("资产预览暂时不可用", 503);
  }
}

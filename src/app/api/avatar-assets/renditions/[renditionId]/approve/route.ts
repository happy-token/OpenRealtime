import {
  authorizeAvatarAssetRequest,
  avatarAssetControlRequest,
  avatarAssetJsonResponse,
  jsonError,
  validAvatarAssetId,
} from "@/lib/avatar-assets-server";

export const dynamic = "force-dynamic";

export async function POST(
  request: Request,
  context: { params: Promise<{ renditionId: string }> },
) {
  if (!authorizeAvatarAssetRequest(request, true)) return jsonError("不允许批准当前画幅", 403);
  const { renditionId } = await context.params;
  if (!validAvatarAssetId(renditionId)) return jsonError("Rendition ID 无效", 400);
  try {
    const payload = await request.json() as { startMs?: unknown; endMs?: unknown; crossfadeMs?: unknown };
    if (![payload.startMs, payload.endMs, payload.crossfadeMs].every(Number.isInteger)) {
      return jsonError("循环区间必须是整数毫秒", 400);
    }
    const response = await avatarAssetControlRequest(
      `/avatar-assets/renditions/${encodeURIComponent(renditionId)}/approve`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          start_ms: payload.startMs,
          end_ms: payload.endMs,
          crossfade_ms: payload.crossfadeMs,
        }),
      },
    );
    return avatarAssetJsonResponse(response, await response.text());
  } catch {
    return jsonError("画幅审核服务暂时不可用", 503);
  }
}

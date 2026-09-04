import {
  authorizeAvatarAssetRequest,
  avatarAssetControlRequest,
  avatarAssetJsonResponse,
  jsonError,
  validAvatarAssetId,
} from "@/lib/avatar-assets-server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const CHECK_FIELDS = [
  "identity_match",
  "single_person",
  "closed_mouth",
  "fixed_camera",
  "no_gestures",
  "rights_confirmed",
] as const;

export async function POST(
  request: Request,
  context: { params: Promise<{ candidateId: string }> },
) {
  if (!authorizeAvatarAssetRequest(request, true)) {
    return jsonError("不允许从当前来源验收动作底片", 403);
  }
  const { candidateId } = await context.params;
  if (!validAvatarAssetId(candidateId)) return jsonError("候选 ID 无效", 400);
  try {
    const payload = await request.json() as { idempotencyKey?: unknown; checks?: Record<string, unknown> };
    if (!validAvatarAssetId(payload.idempotencyKey) || !payload.checks) {
      return jsonError("验收请求无效", 400);
    }
    if (CHECK_FIELDS.some((field) => payload.checks?.[field] !== true)) {
      return jsonError("六项人工验收检查必须全部通过", 400);
    }
    const response = await avatarAssetControlRequest(
      `/avatar-assets/candidates/${encodeURIComponent(candidateId)}/accept`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          idempotency_key: payload.idempotencyKey,
          checks: Object.fromEntries(CHECK_FIELDS.map((field) => [field, true])),
        }),
      },
      15 * 60_000,
    );
    return avatarAssetJsonResponse(response, await response.text());
  } catch (error) {
    console.error("Failed to accept Motion Base Candidate", error);
    return jsonError("候选验收或双画幅生成失败", 503);
  }
}

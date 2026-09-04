import { ADMIN_SESSION_COOKIE } from "./admin-auth";
import { canUseAvatarTestApis, isSameOriginAvatarMutation } from "./avatar-test-access";

const CONTROL_PLANE_URL = process.env.VOICEAGENT_CONTROL_PLANE_URL ?? "http://127.0.0.1:8766";
const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;

export function authorizeAvatarAssetRequest(request: Request, mutation: boolean) {
  const encodedCookie = request.headers.get("cookie")
    ?.split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${ADMIN_SESSION_COOKIE}=`))
    ?.slice(ADMIN_SESSION_COOKIE.length + 1);
  let sessionToken: string | undefined;
  try {
    sessionToken = encodedCookie ? decodeURIComponent(encodedCookie) : undefined;
  } catch {
    return false;
  }
  return canUseAvatarTestApis(request, sessionToken)
    && (!mutation || isSameOriginAvatarMutation(request));
}

export function validAvatarAssetId(value: unknown): value is string {
  return typeof value === "string" && ID_PATTERN.test(value);
}

export async function avatarAssetControlRequest(
  path: string,
  init: RequestInit = {},
  timeoutMs = 60_000,
) {
  if (!path.startsWith("/avatar-assets/") || path.includes("\\")) {
    throw new Error("Invalid avatar asset control path");
  }
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(new URL(path, CONTROL_PLANE_URL), {
      ...init,
      cache: "no-store",
      redirect: "error",
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timeout);
  }
}

export async function persistAvatarCandidate(input: {
  avatarId: string;
  sourceKind: "upload" | "vidu" | "liveportrait" | "ltx" | "minimax";
  sourceId: string;
  logicalName: string;
  mediaType: string;
  idempotencyKey: string;
  bytes: Uint8Array;
}) {
  const query = new URLSearchParams({
    avatar_id: input.avatarId,
    source_kind: input.sourceKind,
    source_id: input.sourceId,
    logical_name: input.logicalName,
    rights_scope: "internal_evaluation",
    idempotency_key: input.idempotencyKey,
  });
  return avatarAssetControlRequest(
    `/avatar-assets/candidates/upload?${query}`,
    {
      method: "POST",
      headers: { "Content-Type": input.mediaType },
      body: input.bytes.slice().buffer as ArrayBuffer,
    },
  );
}

export function avatarAssetJsonResponse(response: Response, body: string) {
  const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";
  if (!contentType.includes("application/json") || !isJson(body)) {
    return jsonError(
      `动作资产服务连接异常（HTTP ${response.status}）`,
      response.ok ? 502 : response.status,
    );
  }
  return new Response(body, {
    status: response.status,
    headers: {
      "Cache-Control": "no-store",
      "Content-Type": "application/json; charset=utf-8",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

function isJson(body: string) {
  try {
    JSON.parse(body);
    return true;
  } catch {
    return false;
  }
}

export function jsonError(error: string, status: number) {
  return Response.json(
    { error },
    { status, headers: { "Cache-Control": "no-store" } },
  );
}

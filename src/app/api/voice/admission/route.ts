import { NextRequest, NextResponse } from "next/server";
import { isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import { USER_SESSION_COOKIE, userFromRequest } from "@/lib/user-session";
import { admitVoiceSession, cancelUnboundVoiceTicket, VoiceAdmissionError } from "@/lib/voice-admission";
import { readLimitedJson, RequestBodyTooLarge } from "@/lib/request-body";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function json(payload: object, status: number) {
  return NextResponse.json(payload, { status, headers: { "Cache-Control": "no-store" } });
}

export async function DELETE(request: NextRequest) {
  if (!isSameOriginAvatarMutation(request)) return json({ code: "invalid_origin", error: "请求来源无效" }, 403);
  try {
    const user = await userFromRequest(request);
    if (!user && request.cookies.has(USER_SESSION_COOKIE)) return json({ code: "login_expired", error: "登录已过期" }, 401);
    const ticket = request.nextUrl.searchParams.get("ticket");
    if (!await cancelUnboundVoiceTicket(user, ticket)) return json({ code: "not_found", error: "会话准入已结束" }, 404);
    return json({ ok: true }, 200);
  } catch {
    return json({ code: "temporarily_unavailable", error: "无法结束未使用的语音准入" }, 503);
  }
}

export async function POST(request: NextRequest) {
  if (!isSameOriginAvatarMutation(request)) return json({ code: "invalid_origin", error: "请求来源无效" }, 403);
  if (process.env.VOICEAGENT_PUBLIC_VOICE_ENABLED !== "true"
    || process.env.VOICEAGENT_ENDPOINT_AUTH_MODE !== "public_ticket") {
    return json({ code: "not_enabled", error: "公开语音体验尚未开放" }, 503);
  }
  try {
    let parsed: { ttsProvider?: unknown; avatarProvider?: unknown } = {};
    try { parsed = await readLimitedJson(request, 512) as typeof parsed ?? {}; }
    catch (error) {
      return error instanceof RequestBodyTooLarge
        ? json({ code: "invalid_request", error: "请求内容过大" }, 413)
        : json({ code: "invalid_request", error: "请求内容无效" }, 400);
    }
    const user = await userFromRequest(request);
    if (!user && request.cookies.has(USER_SESSION_COOKIE)) {
      return json({ code: "login_expired", error: "登录已过期，请重新登录后使用自己的 API Key" }, 401);
    }
    const admission = await admitVoiceSession(user, parsed.ttsProvider, parsed.avatarProvider);
    return json(admission, 200);
  } catch (error) {
    if (error instanceof VoiceAdmissionError) {
      return json({ code: error.code, error: error.message }, error.status);
    }
    return json({ code: "temporarily_unavailable", error: "语音服务暂时不可用，请稍后手动重试" }, 503);
  }
}

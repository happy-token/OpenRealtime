import { NextRequest, NextResponse } from "next/server";
import { ADMIN_SESSION_COOKIE } from "@/lib/admin-auth";
import {
  canUseAvatarTestApis,
  isSameOriginAvatarMutation,
} from "@/lib/avatar-test-access";
import {
  AnamSessionError,
  createAnamSessionToken,
} from "@/lib/anam-session";
import { resolveProviderApiKey } from "@/lib/provider-api-key";
import { USER_SESSION_COOKIE, userFromRequest } from "@/lib/user-session";
import { loadPersonalKeyVersion } from "@/lib/user-provider-credentials";
import { claimAnamVoiceTicket } from "@/lib/voice-admission";
import { readLimitedJson, RequestBodyTooLarge } from "@/lib/request-body";

export const dynamic = "force-dynamic";

function publicAnamFailure(error: AnamSessionError, source: "personal" | "platform") {
  const owner = source === "personal" ? "你的" : "平台";
  if (error.status === 429) return { error: "Anam 当前限制请求，请稍后手动重试", status: 429 };
  if (error.status === 409) return { error: "你的 Anam Key 已更换或清空，请重新开始", status: 409 };
  if (error.status === 402 || /quota|insufficient.*(balance|credit)|余额不足|额度不足|配额不足/i.test(error.message)) {
    return { error: `${owner} Anam 额度不足，${source === "personal" ? "请更新你的 Key" : "请等待平台额度恢复"}`, status: 402 };
  }
  if (error.status === 401 || error.status === 403) {
    return { error: `${owner} Anam Key 无效或无权使用此形象`, status: error.status };
  }
  return { error: "Anam 服务暂时不可用，请稍后手动重试", status: error.status };
}

export async function POST(request: NextRequest) {
  const adminAccess = canUseAvatarTestApis(request, request.cookies.get(ADMIN_SESSION_COOKIE)?.value);
  const publicAccess = process.env.VOICEAGENT_PUBLIC_VOICE_ENABLED === "true"
    && process.env.VOICEAGENT_ENDPOINT_AUTH_MODE === "public_ticket";
  if ((!adminAccess && !publicAccess) || !isSameOriginAvatarMutation(request)) {
    return NextResponse.json(
      { error: "不允许从当前来源创建 Anam 会话" },
      { status: 403, headers: { "Cache-Control": "no-store" } },
    );
  }
  let publicKeySource: "personal" | "platform" | null = null;
  try {
    const payload = await readLimitedJson(request, 1024).catch((error: unknown) => {
      if (error instanceof RequestBodyTooLarge) throw error;
      return {};
    }) as { avatarId?: unknown; admission?: unknown };
    const user = !adminAccess ? await userFromRequest(request) : null;
    if (!adminAccess && request.cookies.has(USER_SESSION_COOKIE) && !user) {
      return NextResponse.json({ error: "登录已过期，请重新登录" }, { status: 401 });
    }
    const requestedAvatarId = typeof payload.avatarId === "string" && payload.avatarId.trim()
      ? payload.avatarId.trim()
      : process.env.ANAM_AVATAR_ID?.trim();
    if (!requestedAvatarId || !/^[a-zA-Z0-9][a-zA-Z0-9._:-]{1,127}$/.test(requestedAvatarId)) {
      return NextResponse.json(
        { error: "请选择有效的 Anam Hosted Avatar" },
        { status: 400, headers: { "Cache-Control": "no-store" } },
      );
    }
    const admission = !adminAccess ? await claimAnamVoiceTicket(user, payload.admission) : null;
    if (!adminAccess && !admission) {
      return NextResponse.json({ error: "语音准入无效，请重新开始" }, { status: 403 });
    }
    if (admission?.source === "platform" && requestedAvatarId !== process.env.ANAM_AVATAR_ID?.trim()) {
      return NextResponse.json({ error: "当前数字人未开放体验" }, { status: 403 });
    }
    publicKeySource = admission?.source ?? null;
    const personalKey = admission?.source === "personal" && user && admission.version
      ? await loadPersonalKeyVersion(user, "anam", admission.version) : null;
    if (admission?.source === "personal" && !personalKey) {
      throw new AnamSessionError("你的 Anam Key 已更换或清空，请重新开始", 409);
    }
    const session = await createAnamSessionToken({
      ANAM_API_KEY: adminAccess
        ? await resolveProviderApiKey(request, "anam")
        : admission?.source === "personal" ? personalKey ?? undefined : process.env.ANAM_API_KEY?.trim(),
      ANAM_AVATAR_ID: requestedAvatarId,
      ANAM_AVATAR_MODEL: process.env.ANAM_AVATAR_MODEL,
    });
    return NextResponse.json(
      {
        session_token: session.sessionToken,
        avatar_id: session.avatarId,
        avatar_model: session.avatarModel,
        mode: "AUDIO_PASSTHROUGH",
      },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch (error) {
    if (error instanceof RequestBodyTooLarge) {
      return NextResponse.json({ error: "请求内容过大" }, { status: 413 });
    }
    const known = error instanceof AnamSessionError;
    const publicFailure = known && publicKeySource
      ? publicAnamFailure(error, publicKeySource) : null;
    return NextResponse.json(
      { error: publicFailure?.error ?? (known && adminAccess ? error.message : "Anam 会话创建失败") },
      {
        status: publicFailure?.status ?? (known ? error.status : 500),
        headers: { "Cache-Control": "no-store" },
      },
    );
  }
}

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

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  if (
    !canUseAvatarTestApis(request, request.cookies.get(ADMIN_SESSION_COOKIE)?.value)
    || !isSameOriginAvatarMutation(request)
  ) {
    return NextResponse.json(
      { error: "不允许从当前来源创建 Anam 会话" },
      { status: 403, headers: { "Cache-Control": "no-store" } },
    );
  }
  try {
    const payload = await request.json().catch(() => ({})) as { avatarId?: unknown };
    const requestedAvatarId = typeof payload.avatarId === "string" && payload.avatarId.trim()
      ? payload.avatarId.trim()
      : process.env.ANAM_AVATAR_ID?.trim();
    if (!requestedAvatarId || !/^[a-zA-Z0-9][a-zA-Z0-9._:-]{1,127}$/.test(requestedAvatarId)) {
      return NextResponse.json(
        { error: "请选择有效的 Anam Hosted Avatar" },
        { status: 400, headers: { "Cache-Control": "no-store" } },
      );
    }
    const session = await createAnamSessionToken({
      ANAM_API_KEY: process.env.ANAM_API_KEY,
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
    const known = error instanceof AnamSessionError;
    return NextResponse.json(
      { error: known ? error.message : "Anam 会话创建失败" },
      {
        status: known ? error.status : 500,
        headers: { "Cache-Control": "no-store" },
      },
    );
  }
}

import { NextRequest, NextResponse } from "next/server";
import { authorizeAvatarAssetRequest } from "@/lib/avatar-assets-server";
import {
  createLiveAvatarSessionToken,
  LiveAvatarSessionError,
} from "@/lib/liveavatar-session";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  if (!authorizeAvatarAssetRequest(request, true)) {
    return NextResponse.json(
      { error: "不允许从当前来源创建 LiveAvatar 会话" },
      { status: 403, headers: { "Cache-Control": "no-store" } },
    );
  }
  try {
    const session = await createLiveAvatarSessionToken({
      LIVEAVATAR_API_KEY: process.env.LIVEAVATAR_API_KEY,
      LIVEAVATAR_AVATAR_ID: process.env.LIVEAVATAR_AVATAR_ID,
      LIVEAVATAR_SANDBOX: process.env.LIVEAVATAR_SANDBOX,
    });
    return NextResponse.json(
      {
        session_token: session.sessionToken,
        session_id: session.sessionId,
        mode: "LITE",
      },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch (error) {
    const known = error instanceof LiveAvatarSessionError;
    return NextResponse.json(
      { error: known ? error.message : "LiveAvatar 会话创建失败" },
      {
        status: known ? error.status : 500,
        headers: { "Cache-Control": "no-store" },
      },
    );
  }
}

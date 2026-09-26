import { NextRequest, NextResponse } from "next/server";
import { isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import { revokeUserSession, USER_SESSION_COOKIE } from "@/lib/user-session";

export const runtime = "nodejs";

export async function POST(request: NextRequest) {
  if (!isSameOriginAvatarMutation(request)) {
    return NextResponse.json({ error: "请求来源无效" }, { status: 403 });
  }
  try {
    await revokeUserSession(request.cookies.get(USER_SESSION_COOKIE)?.value);
  } catch {
    return NextResponse.json({ error: "退出登录失败" }, { status: 503 });
  }
  const response = NextResponse.json({ ok: true });
  response.cookies.set(USER_SESSION_COOKIE, "", {
    httpOnly: true, sameSite: "lax", secure: process.env.NODE_ENV === "production",
    path: "/", maxAge: 0,
  });
  return response;
}

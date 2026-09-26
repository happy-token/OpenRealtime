import { NextRequest, NextResponse } from "next/server";
import { finishOidcLogin, OIDC_FLOW_COOKIE } from "@/lib/user-oidc";
import { createUserSession, USER_SESSION_COOKIE, USER_SESSION_SECONDS } from "@/lib/user-session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const flowCookie = request.cookies.get(OIDC_FLOW_COOKIE)?.value;
  let publicOrigin: URL;
  try {
    publicOrigin = new URL(process.env.VOICEAGENT_PUBLIC_ORIGIN!);
    if ((request.headers.get("host") ?? request.nextUrl.host) !== publicOrigin.host) {
      throw new Error("登录回调来源无效");
    }
    const callbackUrl = new URL(`${request.nextUrl.pathname}${request.nextUrl.search}`, publicOrigin);
    const { issuer, subject, returnTo } = await finishOidcLogin(callbackUrl, flowCookie);
    const token = await createUserSession({ issuer, subject });
    const response = NextResponse.redirect(new URL(returnTo, publicOrigin));
    response.cookies.set(USER_SESSION_COOKIE, token, {
      httpOnly: true, sameSite: "lax", secure: process.env.NODE_ENV === "production",
      path: "/", maxAge: USER_SESSION_SECONDS,
    });
    response.cookies.set(OIDC_FLOW_COOKIE, "", {
      httpOnly: true, sameSite: "lax", secure: process.env.NODE_ENV === "production",
      path: "/api/user/callback", maxAge: 0,
    });
    return response;
  } catch {
    return NextResponse.redirect(new URL(
      "/settings/providers?loginError=provider",
      process.env.VOICEAGENT_PUBLIC_ORIGIN || request.url,
    ));
  }
}

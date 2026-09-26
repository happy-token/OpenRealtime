import { NextRequest, NextResponse } from "next/server";
import { beginOidcLogin, OIDC_FLOW_COOKIE, safeReturnPath } from "@/lib/user-oidc";
import { missingUserAccountSettings } from "@/lib/user-account-setup";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  if (missingUserAccountSettings().length > 0) {
    return NextResponse.redirect(new URL("/settings/providers", request.url));
  }
  try {
    const publicOrigin = new URL(process.env.VOICEAGENT_PUBLIC_ORIGIN!);
    const requestHost = request.headers.get("host") ?? request.nextUrl.host;
    if (requestHost !== publicOrigin.host) {
      return NextResponse.redirect(new URL(
        `/api/user/login?next=${encodeURIComponent(safeReturnPath(request.nextUrl.searchParams.get("next")))}`,
        publicOrigin,
      ));
    }
    const { redirectUrl, flowCookie } = await beginOidcLogin(
      safeReturnPath(request.nextUrl.searchParams.get("next")),
    );
    const response = NextResponse.redirect(redirectUrl);
    response.cookies.set(OIDC_FLOW_COOKIE, flowCookie, {
      httpOnly: true, sameSite: "lax", secure: process.env.NODE_ENV === "production",
      path: "/api/user/callback", maxAge: 10 * 60,
    });
    return response;
  } catch {
    return NextResponse.redirect(new URL("/settings/providers?loginError=provider", request.url));
  }
}

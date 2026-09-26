import { NextRequest, NextResponse } from "next/server";
import { ADMIN_SESSION_COOKIE } from "@/lib/admin-auth";
import { canUseAvatarTestApis, isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import {
  providerApiKey, providerKeyCookieName, sealProviderKey, type UserKeyProvider,
} from "@/lib/provider-api-key";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

function authorized(request: NextRequest) {
  return canUseAvatarTestApis(request, request.cookies.get(ADMIN_SESSION_COOKIE)?.value);
}

function parseProvider(value: unknown): UserKeyProvider | null {
  return value === "anam" || value === "minimax" ? value : null;
}

export async function GET(request: NextRequest) {
  if (!authorized(request)) return NextResponse.json({ error: "无权读取凭据状态" }, { status: 403 });
  const provider = parseProvider(request.nextUrl.searchParams.get("provider"));
  if (!provider) return NextResponse.json({ error: "服务商无效" }, { status: 400 });
  return NextResponse.json({ configured: Boolean(providerApiKey(request, provider)) }, {
    headers: { "Cache-Control": "no-store" },
  });
}

export async function POST(request: NextRequest) {
  if (!authorized(request) || !isSameOriginAvatarMutation(request)) {
    return NextResponse.json({ error: "无权设置服务商凭据" }, { status: 403 });
  }
  const body = await request.json().catch(() => null) as { provider?: unknown; apiKey?: unknown } | null;
  const provider = parseProvider(body?.provider);
  const apiKey = body?.apiKey;
  if (!provider || typeof apiKey !== "string" || apiKey.length < 8 || apiKey.length > 512 || apiKey !== apiKey.trim() || /[\x00-\x1f\x7f]/.test(apiKey)) {
    return NextResponse.json({ error: "请填写有效的 API Key" }, { status: 400 });
  }
  try {
    const response = NextResponse.json({ configured: true }, { headers: { "Cache-Control": "no-store" } });
    response.cookies.set(providerKeyCookieName(provider), sealProviderKey(apiKey), {
      httpOnly: true, sameSite: "strict", secure: process.env.NODE_ENV === "production", path: "/",
    });
    return response;
  } catch {
    return NextResponse.json({ error: "用户 API Key 会话加密尚未配置" }, { status: 503 });
  }
}

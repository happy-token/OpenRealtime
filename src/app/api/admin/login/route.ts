import { NextRequest, NextResponse } from "next/server";
import {
  ADMIN_SESSION_COOKIE,
  ADMIN_SESSION_MAX_AGE_SECONDS,
  adminAuthConfigFromEnv,
  createAdminSessionToken,
  verifyAdminCredentials,
} from "@/lib/admin-auth";

const attempts = new Map<string, { failures: number; resetAt: number }>();
const WINDOW_MS = 15 * 60 * 1000;
const MAX_FAILURES = 5;

export async function POST(request: NextRequest) {
  const config = adminAuthConfigFromEnv();
  if (!config) {
    return NextResponse.json({ error: "管理员账户尚未配置" }, { status: 503 });
  }
  const client = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ?? "local";
  const now = Date.now();
  const state = attempts.get(client);
  if (state && state.resetAt > now && state.failures >= MAX_FAILURES) {
    return NextResponse.json({ error: "登录尝试过多，请稍后再试" }, { status: 429 });
  }
  let body: { username?: unknown; password?: unknown };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "请求格式错误" }, { status: 400 });
  }
  const username = typeof body.username === "string" ? body.username.slice(0, 128) : "";
  const password = typeof body.password === "string" ? body.password.slice(0, 512) : "";
  if (!verifyAdminCredentials(username, password, config)) {
    const current = state && state.resetAt > now ? state : { failures: 0, resetAt: now + WINDOW_MS };
    attempts.set(client, { ...current, failures: current.failures + 1 });
    return NextResponse.json({ error: "账户或密码错误" }, { status: 401 });
  }
  attempts.delete(client);
  const response = NextResponse.json({ username: config.username });
  response.cookies.set(ADMIN_SESSION_COOKIE, createAdminSessionToken(config), {
    httpOnly: true,
    sameSite: "strict",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: ADMIN_SESSION_MAX_AGE_SECONDS,
  });
  return response;
}

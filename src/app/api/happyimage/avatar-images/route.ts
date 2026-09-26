import { NextRequest, NextResponse } from "next/server";
import { ADMIN_SESSION_COOKIE } from "@/lib/admin-auth";
import { canUseAvatarTestApis, isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import { createHappyImageAvatar, HappyImageAvatarError } from "@/lib/happyimage-avatar";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const maxDuration = 120;

export async function POST(request: NextRequest) {
  if (
    !canUseAvatarTestApis(request, request.cookies.get(ADMIN_SESSION_COOKIE)?.value)
    || !isSameOriginAvatarMutation(request)
  ) {
    return json({ error: "不允许从当前来源生成 HappyImage 图片" }, 403);
  }
  try {
    const payload = await request.json() as { prompt?: unknown };
    if (typeof payload.prompt !== "string") return json({ error: "请填写形象描述" }, 400);
    const result = await createHappyImageAvatar({
      HAPPYIMAGE_API_URL: process.env.HAPPYIMAGE_API_URL,
      HAPPYIMAGE_API_KEY: process.env.HAPPYIMAGE_API_KEY,
    }, { prompt: payload.prompt });
    return json({ imageUrl: result.imageUrl }, 201);
  } catch (error) {
    const known = error instanceof HappyImageAvatarError;
    return json({ error: known ? error.message : "HappyImage 生成失败" }, known ? error.status : 500);
  }
}

function json(payload: object, status: number) {
  return NextResponse.json(payload, { status, headers: { "Cache-Control": "no-store" } });
}

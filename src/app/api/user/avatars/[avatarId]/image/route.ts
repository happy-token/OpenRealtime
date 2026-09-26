import { NextRequest } from "next/server";
import { readPersonalAvatarImage } from "@/lib/personal-avatar-library";
import { userFromRequest } from "@/lib/user-session";
import { privateMediaResponse } from "@/lib/private-media-response";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Context = { params: Promise<{ avatarId: string }> };

export async function GET(request: NextRequest, context: Context) {
  const user = await userFromRequest(request);
  if (!user) return Response.json({ error: "请先登录" }, { status: 401 });
  try {
    const image = await readPersonalAvatarImage(user, (await context.params).avatarId);
    if (!image) return Response.json({ error: "找不到个人数字人图片" }, { status: 404 });
    return privateMediaResponse(request, image);
  } catch {
    return Response.json({ error: "个人数字人图片暂时不可用" }, { status: 503 });
  }
}

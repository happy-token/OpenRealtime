import { NextRequest } from "next/server";
import { isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import { attachPersonalMotionToAvatar } from "@/lib/personal-avatar-library";
import { readLimitedJson, RequestBodyTooLarge } from "@/lib/request-body";
import { userFromRequest } from "@/lib/user-session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Context = { params: Promise<{ avatarId: string }> };

export async function POST(request: NextRequest, context: Context) {
  if (!isSameOriginAvatarMutation(request)) return Response.json({ error: "请求来源无效" }, { status: 403 });
  const user = await userFromRequest(request);
  if (!user) return Response.json({ error: "请先登录" }, { status: 401 });
  let body: { motionId?: unknown } | null;
  try {
    body = await readLimitedJson(request, 1024) as { motionId?: unknown } | null;
  } catch (error) {
    return Response.json({ error: error instanceof RequestBodyTooLarge ? "请求内容过大" : "请求内容无效" }, { status: error instanceof RequestBodyTooLarge ? 413 : 400 });
  }
  if (typeof body?.motionId !== "string" || !/^[a-f0-9]{64}$/.test(body.motionId)) return Response.json({ error: "动作素材 ID 无效" }, { status: 400 });
  try {
    const action = await attachPersonalMotionToAvatar(user, (await context.params).avatarId, body.motionId);
    return Response.json({ action }, { status: 201, headers: { "Cache-Control": "private, no-store" } });
  } catch (error) {
    const message = error instanceof Error ? error.message : "关联动作素材失败";
    return Response.json({ error: message }, { status: message.includes("找不到") ? 404 : message.includes("无效") ? 400 : 503 });
  }
}

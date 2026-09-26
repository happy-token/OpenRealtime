import { NextRequest } from "next/server";
import { isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import { updatePersonalAvatarAction } from "@/lib/personal-avatar-library";
import { readLimitedJson, RequestBodyTooLarge } from "@/lib/request-body";
import { userFromRequest } from "@/lib/user-session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Context = { params: Promise<{ avatarId: string; avatarActionId: string }> };

export async function PATCH(request: NextRequest, context: Context) {
  if (!isSameOriginAvatarMutation(request)) return Response.json({ error: "请求来源无效" }, { status: 403 });
  const user = await userFromRequest(request);
  if (!user) return Response.json({ error: "请先登录" }, { status: 401 });
  let body: { operation?: unknown; displayName?: unknown } | null;
  try {
    body = await readLimitedJson(request, 2048) as typeof body;
  } catch (error) {
    return Response.json({ error: error instanceof RequestBodyTooLarge ? "请求内容过大" : "请求内容无效" }, { status: error instanceof RequestBodyTooLarge ? 413 : 400 });
  }
  const update = body?.operation === "rename" && typeof body.displayName === "string"
    ? { displayName: body.displayName }
    : null;
  if (!update) return Response.json({ error: "个人动作更新操作无效" }, { status: 400 });
  try {
    const { avatarId, avatarActionId } = await context.params;
    const action = await updatePersonalAvatarAction(user, avatarId, avatarActionId, update);
    return Response.json({ action }, { headers: { "Cache-Control": "private, no-store" } });
  } catch (error) {
    const message = error instanceof Error ? error.message : "";
    const status = message.includes("找不到") ? 404 : /无效|请填写/.test(message) ? 400 : 503;
    if (status === 503) console.error("Failed to rename personal avatar action", error);
    return Response.json({ error: status === 503 ? "个人动作更新失败" : message }, { status });
  }
}

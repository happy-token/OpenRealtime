import { NextRequest } from "next/server";
import { isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import { findPersonalAvatar, renamePersonalAvatar } from "@/lib/personal-avatar-library";
import { readLimitedJson, RequestBodyTooLarge } from "@/lib/request-body";
import { userFromRequest } from "@/lib/user-session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Context = { params: Promise<{ avatarId: string }> };

export async function GET(request: NextRequest, context: Context) {
  const user = await userFromRequest(request);
  if (!user) return Response.json({ error: "请先登录" }, { status: 401 });
  const { avatarId } = await context.params;
  try {
    const avatar = await findPersonalAvatar(user, avatarId);
    if (!avatar) return Response.json({ error: "找不到个人数字人" }, { status: 404 });
    return Response.json({ avatar: {
      avatar_id: avatar.id,
      display_name: avatar.name,
      source_image_url: `/api/user/avatars/${avatar.id}/image`,
      created_at: avatar.createdAt,
      updated_at: avatar.updatedAt,
      deleted_at: avatar.deletedAt,
      realtime_binding: null,
      actions: avatar.actions,
    } }, { headers: { "Cache-Control": "private, no-store" } });
  } catch {
    return Response.json({ error: "个人数字人目录暂时不可用" }, { status: 503 });
  }
}

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
  if (body?.operation !== "rename" || typeof body.displayName !== "string") {
    return Response.json({ error: "个人数字人更新操作无效" }, { status: 400 });
  }
  try {
    const avatar = await renamePersonalAvatar(user, (await context.params).avatarId, body.displayName);
    return Response.json({ avatar }, { headers: { "Cache-Control": "private, no-store" } });
  } catch (error) {
    const message = error instanceof Error ? error.message : "";
    const status = message.includes("找不到") ? 404 : /无效|请填写/.test(message) ? 400 : 503;
    if (status === 503) console.error("Failed to rename personal avatar", error);
    return Response.json({ error: status === 503 ? "个人数字人更新失败" : message }, { status });
  }
}

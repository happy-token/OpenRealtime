import { isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import { acceptLipForcingJob } from "@/lib/lipforcing-talking-worker";
import { findPersonalAvatar } from "@/lib/personal-avatar-library";
import { readLimitedJson } from "@/lib/request-body";
import { userFromRequest } from "@/lib/user-session";

export const runtime = "nodejs";
type Context = { params: Promise<{ avatarId: string; avatarActionId: string }> };
const json = (body: object, status = 200) => Response.json(body, { status, headers: { "Cache-Control": "private, no-store" } });

export async function POST(request: Request, context: Context) {
  if (!isSameOriginAvatarMutation(request)) return json({ error: "请求来源无效" }, 403);
  const user = await userFromRequest(request);
  if (!user) return json({ error: "请先登录" }, 401);
  const { avatarId, avatarActionId } = await context.params;
  const avatar = await findPersonalAvatar(user, avatarId);
  if (!avatar || avatar.deletedAt || !avatar.actions.some((item) => item.avatar_action_id === avatarActionId && !item.deleted_at)) return json({ error: "找不到动作底片" }, 404);
  try {
    const body = await readLimitedJson(request, 256) as { jobId?: unknown };
    if (typeof body?.jobId !== "string" || !/^lipforcing-[0-9a-f-]{36}$/.test(body.jobId)) return json({ error: "任务 ID 无效" }, 400);
    return json(await acceptLipForcingJob(avatarId, avatarActionId, body.jobId, user));
  } catch (error) { return json({ error: error instanceof Error ? error.message : "保存口型对齐失败" }, 400); }
}

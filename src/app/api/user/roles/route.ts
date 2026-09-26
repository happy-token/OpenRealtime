import { isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import { createPersonalRole, listPersonalRoles, type PersonalRoleInput } from "@/lib/personal-role-library";
import { readLimitedJson, RequestBodyTooLarge } from "@/lib/request-body";
import { userFromRequest } from "@/lib/user-session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const json = (value: object, status = 200) => Response.json(value, { status, headers: { "Cache-Control": "private, no-store" } });

export async function GET(request: Request) {
  const user = await userFromRequest(request);
  if (!user) return json({ error: "请先登录" }, 401);
  try { return json({ roles: await listPersonalRoles(user) }); }
  catch { return json({ error: "个人角色目录暂时不可用" }, 503); }
}

export async function POST(request: Request) {
  if (!isSameOriginAvatarMutation(request)) return json({ error: "请求来源无效" }, 403);
  const user = await userFromRequest(request);
  if (!user) return json({ error: "请先登录" }, 401);
  try {
    const input = await readLimitedJson(request, 2_000) as PersonalRoleInput;
    return json({ role: await createPersonalRole(user, input) }, 201);
  } catch (error) {
    if (error instanceof RequestBodyTooLarge) return json({ error: "请求内容过大" }, 413);
    const message = error instanceof Error ? error.message : "角色创建失败";
    return json({ error: message }, /无效|自己的|上限/.test(message) ? 400 : 503);
  }
}

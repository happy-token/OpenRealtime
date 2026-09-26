import { isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import { deletePersonalRole, findPersonalRole, updatePersonalRole, type PersonalRoleInput } from "@/lib/personal-role-library";
import { readLimitedJson, RequestBodyTooLarge } from "@/lib/request-body";
import { userFromRequest } from "@/lib/user-session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Context = { params: Promise<{ roleId: string }> };
const json = (value: object, status = 200) => Response.json(value, { status, headers: { "Cache-Control": "private, no-store" } });

export async function GET(request: Request, context: Context) {
  const user = await userFromRequest(request);
  if (!user) return json({ error: "请先登录" }, 401);
  try {
    const role = await findPersonalRole(user, (await context.params).roleId);
    return role ? json({ role }) : json({ error: "角色不存在" }, 404);
  } catch { return json({ error: "个人角色目录暂时不可用" }, 503); }
}

export async function PATCH(request: Request, context: Context) {
  if (!isSameOriginAvatarMutation(request)) return json({ error: "请求来源无效" }, 403);
  const user = await userFromRequest(request);
  if (!user) return json({ error: "请先登录" }, 401);
  try {
    const input = await readLimitedJson(request, 2_000) as PersonalRoleInput;
    const role = await updatePersonalRole(user, (await context.params).roleId, input);
    return role ? json({ role }) : json({ error: "角色不存在" }, 404);
  } catch (error) {
    if (error instanceof RequestBodyTooLarge) return json({ error: "请求内容过大" }, 413);
    const message = error instanceof Error ? error.message : "角色保存失败";
    return json({ error: message }, /无效|自己的/.test(message) ? 400 : 503);
  }
}

export async function DELETE(request: Request, context: Context) {
  if (!isSameOriginAvatarMutation(request)) return json({ error: "请求来源无效" }, 403);
  const user = await userFromRequest(request);
  if (!user) return json({ error: "请先登录" }, 401);
  try {
    return await deletePersonalRole(user, (await context.params).roleId)
      ? json({ deleted: true })
      : json({ error: "角色不存在" }, 404);
  } catch {
    return json({ error: "角色删除失败" }, 503);
  }
}

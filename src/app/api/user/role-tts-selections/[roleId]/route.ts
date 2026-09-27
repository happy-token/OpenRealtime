import { isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import { findPersonalRole } from "@/lib/personal-role-library";
import { findRole } from "@/lib/role-catalog-repository";
import { clearRoleTtsTarget, getRoleTtsTarget, isRoleTtsTarget, resolveRoleTtsTarget, saveRoleTtsTarget } from "@/lib/role-tts-selections";
import { readLimitedJson, RequestBodyTooLarge } from "@/lib/request-body";
import { userFromRequest, type WebUser } from "@/lib/user-session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
type Context = { params: Promise<{ roleId: string }> };
const json = (value: object, status = 200) => Response.json(value, { status, headers: { "Cache-Control": "private, no-store" } });

async function accessibleRole(user: WebUser, roleId: string) {
  return roleId.startsWith("role-personal-") ? findPersonalRole(user, roleId) : findRole(roleId);
}

export async function GET(request: Request, context: Context) {
  const user = await userFromRequest(request);
  if (!user) return json({ error: "请先登录" }, 401);
  try {
    const { roleId } = await context.params;
    if (!await accessibleRole(user, roleId)) return json({ error: "角色不存在" }, 404);
    return json({ target: await getRoleTtsTarget(user, roleId) });
  } catch { return json({ error: "角色语音配置暂不可用" }, 503); }
}

export async function PUT(request: Request, context: Context) {
  if (!isSameOriginAvatarMutation(request)) return json({ error: "请求来源无效" }, 403);
  const user = await userFromRequest(request);
  if (!user) return json({ error: "请先登录" }, 401);
  try {
    const { roleId } = await context.params;
    if (!await accessibleRole(user, roleId)) return json({ error: "角色不存在" }, 404);
    const body = await readLimitedJson(request, 256) as { target?: unknown };
    if (!isRoleTtsTarget(body?.target)) return json({ error: "角色语音配置无效" }, 400);
    const resolved = await resolveRoleTtsTarget(user, body.target);
    if (!resolved) return json({ error: "配置不可用，或尚未通过实时测试" }, 400);
    await saveRoleTtsTarget(user, roleId, body.target);
    return json({ target: body.target, provider: resolved.provider, scope: resolved.scope });
  } catch (error) {
    if (error instanceof RequestBodyTooLarge) return json({ error: "请求内容过大" }, 413);
    return json({ error: "保存角色语音配置失败" }, 503);
  }
}

export async function DELETE(request: Request, context: Context) {
  if (!isSameOriginAvatarMutation(request)) return json({ error: "请求来源无效" }, 403);
  const user = await userFromRequest(request);
  if (!user) return json({ error: "请先登录" }, 401);
  try {
    const { roleId } = await context.params;
    if (!await accessibleRole(user, roleId)) return json({ error: "角色不存在" }, 404);
    await clearRoleTtsTarget(user, roleId);
    return json({ target: null });
  } catch { return json({ error: "恢复默认语音配置失败" }, 503); }
}

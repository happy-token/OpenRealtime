import { isSameOriginAvatarMutation } from "@/lib/avatar-test-access";
import { defaultRoleOwner } from "@/lib/default-role-owner";
import { findPersonalRole } from "@/lib/personal-role-library";
import { readLimitedJson, RequestBodyTooLarge } from "@/lib/request-body";
import { findRole } from "@/lib/role-catalog-repository";
import { readUserDefaultRole, writeUserDefaultRole } from "@/lib/user-default-role";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
const json = (body: object, status = 200) => Response.json(body, { status, headers: { "Cache-Control": "private, no-store" } });

export async function GET(request: Request) {
  const user = await defaultRoleOwner(request);
  if (!user) return json({ error: "请先登录" }, 401);
  try { return json({ roleId: await readUserDefaultRole(user) ?? "default-assistant" }); }
  catch { return json({ error: "默认角色读取失败" }, 503); }
}

export async function PUT(request: Request) {
  if (!isSameOriginAvatarMutation(request)) return json({ error: "请求来源无效" }, 403);
  const user = await defaultRoleOwner(request, true);
  if (!user) return json({ error: "请先登录" }, 401);
  try {
    const body = await readLimitedJson(request, 512) as { roleId?: unknown };
    if (typeof body?.roleId !== "string") return json({ error: "角色 ID 无效" }, 400);
    const role = body.roleId.startsWith("role-personal-")
      ? await findPersonalRole(user, body.roleId)
      : await findRole(body.roleId);
    if (!role) return json({ error: "角色不存在" }, 404);
    await writeUserDefaultRole(user, role.role_id);
    return json({ roleId: role.role_id });
  } catch (error) {
    if (error instanceof RequestBodyTooLarge) return json({ error: "请求内容过大" }, 413);
    return json({ error: error instanceof Error ? error.message : "默认角色保存失败" }, 503);
  }
}

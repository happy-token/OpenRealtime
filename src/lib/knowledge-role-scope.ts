import { findRole } from "./role-catalog-repository";
import { findPersonalRole } from "./personal-role-library";
import { avatarIdFromHostedRoleId } from "./hosted-avatar-role-id";
import { userFromRequest } from "./user-session";
import { jsonError } from "./avatar-assets-server";

export async function requireKnowledgeRole(request: Request, roleId: unknown): Promise<string | Response> {
  if (typeof roleId !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._:-]{1,159}$/.test(roleId)) {
    return jsonError("请先选择有效角色", 400);
  }
  // Hosted settings already use an owner-scoped avatar namespace; no other
  // user's documents are accessible even when the avatar ID is shared.
  if (avatarIdFromHostedRoleId(roleId)) return roleId;
  const user = roleId.startsWith("role-personal-") ? await userFromRequest(request) : null;
  const role = roleId.startsWith("role-personal-")
    ? user ? await findPersonalRole(user, roleId) : null : await findRole(roleId);
  return role ? roleId : jsonError("角色不存在", 404);
}

export function knowledgeError(error: unknown) {
  const message = error instanceof Error ? error.message : "知识库操作失败";
  return jsonError(message, /冲突/.test(message) ? 409 : /不可访问/.test(message) ? 403
    : /无效|已存在|上限|无法读取|没有|编码|过长|支持|过大|非公开|跳转/.test(message) ? 400 : 503);
}

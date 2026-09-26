import { findRole } from "./role-catalog-repository";
import { findPersonalRole } from "./personal-role-library";
import { userFromRequest } from "./user-session";
import { getHostedAvatarSettings } from "./hosted-avatar-settings-repository";
import { avatarIdFromHostedRoleId } from "./hosted-avatar-role-id";
import { conversationOwner } from "./conversation-history-auth";

export async function memoryRoleForRequest(request: Request, roleId: string) {
  const hostedAvatarId = avatarIdFromHostedRoleId(roleId);
  if (hostedAvatarId) {
    const owner = await conversationOwner(request);
    if (owner instanceof Response) return null;
    const settings = await getHostedAvatarSettings(owner, hostedAvatarId);
    return settings ? { role_id: roleId, memory_enabled: settings.memory_enabled } : null;
  }
  if (roleId.startsWith("role-personal-")) {
    const user = await userFromRequest(request);
    return user ? findPersonalRole(user, roleId) : null;
  }
  return findRole(roleId);
}

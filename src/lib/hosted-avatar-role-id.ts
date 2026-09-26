const AVATAR_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{1,119}$/;
const ROLE_PREFIX = "hosted-avatar-";

export function hostedAvatarRoleId(avatarId: string) {
  if (!AVATAR_ID.test(avatarId)) throw new Error("实时数字人 ID 无效");
  return `${ROLE_PREFIX}${avatarId}`;
}

export function avatarIdFromHostedRoleId(roleId: string) {
  if (!roleId.startsWith(ROLE_PREFIX)) return null;
  const avatarId = roleId.slice(ROLE_PREFIX.length);
  return AVATAR_ID.test(avatarId) ? avatarId : null;
}

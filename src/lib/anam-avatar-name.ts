export const ANAM_AVATAR_NAME_MIN_LENGTH = 3;
export const ANAM_AVATAR_NAME_MAX_LENGTH = 50;
export const ANAM_AVATAR_NAME_REQUIREMENT = "Anam 形象名称需要 3 到 50 个字符";

export function isValidAnamAvatarName(value: string) {
  const length = value.trim().length;
  return length >= ANAM_AVATAR_NAME_MIN_LENGTH && length <= ANAM_AVATAR_NAME_MAX_LENGTH;
}

export function suggestAnamAvatarName(value: string) {
  const trimmed = value.trim().slice(0, ANAM_AVATAR_NAME_MAX_LENGTH);
  if (trimmed.length >= ANAM_AVATAR_NAME_MIN_LENGTH) return trimmed;
  return `${trimmed}数字人`.slice(0, ANAM_AVATAR_NAME_MAX_LENGTH);
}

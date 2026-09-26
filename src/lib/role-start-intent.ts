const STORAGE_KEY = "openrealtime-role-start-intent";
const MAX_AGE_MS = 30_000;

export function saveRoleStartIntent(roleId: string) {
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ roleId, createdAt: Date.now() }));
  } catch { /* Role selection still works if session storage is unavailable. */ }
}

export function consumeRoleStartIntent(roleId: string): boolean {
  let raw: string | null;
  try {
    raw = window.sessionStorage.getItem(STORAGE_KEY);
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    return false;
  }
  if (!raw) return false;
  try {
    const intent = JSON.parse(raw) as { roleId?: unknown; createdAt?: unknown };
    return intent.roleId === roleId
      && typeof intent.createdAt === "number"
      && Date.now() - intent.createdAt >= 0
      && Date.now() - intent.createdAt <= MAX_AGE_MS;
  } catch {
    return false;
  }
}

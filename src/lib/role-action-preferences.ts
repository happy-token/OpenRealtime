const STORAGE_PREFIX = "openrealtime:role-action-preferences:";
const ORDER_PREFIX = "openrealtime:avatar-action-order:";
export const AVATAR_ACTION_ORDER_CHANGED = "openrealtime:avatar-action-order-changed";

export function readAvatarActionOrder(avatarId: string): string[] {
  if (typeof window === "undefined" || !avatarId) return [];
  try {
    const stored: unknown = JSON.parse(window.localStorage.getItem(`${ORDER_PREFIX}${avatarId}`) ?? "null");
    if (Array.isArray(stored)) return stored.filter((id): id is string => typeof id === "string");
    for (let index = 0; index < window.localStorage.length; index++) {
      const key = window.localStorage.key(index);
      if (!key?.startsWith(STORAGE_PREFIX) || !key.endsWith(`:${avatarId}`)) continue;
      const legacy = JSON.parse(window.localStorage.getItem(key) ?? "null");
      if (Array.isArray(legacy?.order) && legacy.order.length) return legacy.order.filter((id: unknown): id is string => typeof id === "string");
    }
  } catch { /* Use catalog order when storage is unavailable. */ }
  return [];
}

export function rememberAvatarActionOrder(avatarId: string, order: string[]) {
  if (typeof window === "undefined" || !avatarId) return;
  try {
    window.localStorage.setItem(`${ORDER_PREFIX}${avatarId}`, JSON.stringify([...new Set(order)]));
    window.dispatchEvent(new Event(AVATAR_ACTION_ORDER_CHANGED));
  } catch { /* The current list remains sortable without storage. */ }
}

export interface RoleActionPreferences {
  order: string[];
  actionId?: string;
  variantId?: string;
  variants: Record<string, string>;
}

function storageKey(roleId: string, avatarId: string) {
  return `${STORAGE_PREFIX}${roleId}:${avatarId}`;
}

export function readRoleActionPreferences(roleId: string, avatarId: string): RoleActionPreferences {
  const empty: RoleActionPreferences = { order: readAvatarActionOrder(avatarId), variants: {} };
  if (typeof window === "undefined" || !roleId || !avatarId) return empty;
  try {
    const value: unknown = JSON.parse(window.localStorage.getItem(storageKey(roleId, avatarId)) ?? "null");
    if (!value || typeof value !== "object") return empty;
    const record = value as Record<string, unknown>;
    const variants = record.variants && typeof record.variants === "object" && !Array.isArray(record.variants)
      ? Object.fromEntries(Object.entries(record.variants).filter((entry): entry is [string, string] => typeof entry[1] === "string")) : {};
    return {
      order: empty.order.length ? empty.order : Array.isArray(record.order) ? record.order.filter((id): id is string => typeof id === "string") : [],
      actionId: typeof record.actionId === "string" ? record.actionId : undefined,
      variantId: typeof record.variantId === "string" ? record.variantId : undefined,
      variants,
    };
  } catch {
    return empty;
  }
}

function save(roleId: string, avatarId: string, value: RoleActionPreferences) {
  if (typeof window === "undefined" || !roleId || !avatarId) return;
  try {
    window.localStorage.setItem(storageKey(roleId, avatarId), JSON.stringify(value));
  } catch {
    // Preview choices still work when browser storage is unavailable.
  }
}

export function rememberRoleActionSelection(roleId: string, avatarId: string, actionId: string, variantId?: string) {
  const current = readRoleActionPreferences(roleId, avatarId);
  save(roleId, avatarId, {
    ...current,
    actionId,
    variantId,
    variants: variantId ? { ...current.variants, [actionId]: variantId } : current.variants,
  });
}

export function rememberRoleActionOrder(roleId: string, avatarId: string, order: string[]) {
  const current = readRoleActionPreferences(roleId, avatarId);
  save(roleId, avatarId, { ...current, order: [...new Set(order)] });
  rememberAvatarActionOrder(avatarId, order);
}

export function orderRoleActions<T>(actions: T[], order: string[], getId: (action: T) => string): T[] {
  const positions = new Map(order.map((id, index) => [id, index]));
  return actions.map((action, index) => ({ action, index })).sort((a, b) =>
    (positions.get(getId(a.action)) ?? Infinity) - (positions.get(getId(b.action)) ?? Infinity) || a.index - b.index,
  ).map(({ action }) => action);
}

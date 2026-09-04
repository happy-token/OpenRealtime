export const AVATAR_DISPLAY_CONFIG_STORAGE_KEY = "voice-agent-avatar-display-config";
export const EXPERIENCE_MODE_STORAGE_KEY = "voice-agent-experience-mode";
export const CUSTOM_AVATAR_IDENTITY_STORAGE_KEY = "openrealtime-custom-avatar-identity";
export const AVATAR_IDENTITY_DISPLAY_NAMES_STORAGE_KEY = "openrealtime-avatar-identity-display-names";
export const AVATAR_IDENTITY_UPDATED_EVENT = "openrealtime:avatar-identity-updated";

export type StoredCustomAvatarIdentity = {
  identityId: string;
  name: string;
  dataUrl: string;
  sourceSha256: string;
  updatedAt: string;
};

type StoredCustomAvatarCatalog = {
  version: 2;
  selectedIdentityId: string;
  identities: StoredCustomAvatarIdentity[];
};

const MAX_LOCAL_IDENTITIES = 4;
const MAX_DISPLAY_NAME_LENGTH = 40;

export function readStoredAvatarIdentityDisplayName(identityId: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const names = readDisplayNames();
  return names[identityId] || fallback;
}

export function storeAvatarIdentityDisplayName(identityId: string, requestedName: string): string {
  if (typeof window === "undefined") return requestedName.trim();
  const names = readDisplayNames();
  const base = requestedName.trim().slice(0, MAX_DISPLAY_NAME_LENGTH) || "未命名数字人";
  const used = new Set(
    Object.entries(names)
      .filter(([id]) => id !== identityId)
      .map(([, name]) => name.toLocaleLowerCase()),
  );
  let unique = base;
  let suffix = 2;
  while (used.has(unique.toLocaleLowerCase())) {
    const ending = ` ${suffix}`;
    unique = `${base.slice(0, MAX_DISPLAY_NAME_LENGTH - ending.length)}${ending}`;
    suffix += 1;
  }
  window.localStorage.setItem(AVATAR_IDENTITY_DISPLAY_NAMES_STORAGE_KEY, JSON.stringify({ ...names, [identityId]: unique }));
  if (typeof CustomEvent !== "undefined") window.dispatchEvent(new CustomEvent(AVATAR_IDENTITY_UPDATED_EVENT));
  return unique;
}

function readDisplayNames(): Record<string, string> {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(AVATAR_IDENTITY_DISPLAY_NAMES_STORAGE_KEY) ?? "{}") as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    return Object.fromEntries(Object.entries(parsed).filter(([id, name]) => (
      /^[a-zA-Z0-9][a-zA-Z0-9._:-]{1,127}$/.test(id)
      && typeof name === "string"
      && Boolean(name.trim())
    )));
  } catch {
    return {};
  }
}

export function readStoredCustomAvatarIdentity(): StoredCustomAvatarIdentity | null {
  const catalog = readStoredCustomAvatarCatalog();
  return catalog.identities.find((identity) => identity.identityId === catalog.selectedIdentityId)
    ?? catalog.identities.at(-1)
    ?? null;
}

export function readStoredCustomAvatarIdentities(): StoredCustomAvatarIdentity[] {
  return readStoredCustomAvatarCatalog().identities;
}

export function renameStoredCustomAvatarIdentity(
  identityId: string,
  requestedName: string,
): StoredCustomAvatarIdentity | null {
  if (typeof window === "undefined") return null;
  const catalog = readStoredCustomAvatarCatalog();
  const current = catalog.identities.find((identity) => identity.identityId === identityId);
  if (!current) return null;
  const name = requestedName.trim().slice(0, MAX_DISPLAY_NAME_LENGTH) || "未命名数字人";
  const identities = catalog.identities.map((identity) => identity.identityId === identityId
    ? { ...identity, name, updatedAt: new Date().toISOString() }
    : identity);
  persistCatalog({ ...catalog, identities });
  window.dispatchEvent(new CustomEvent(AVATAR_IDENTITY_UPDATED_EVENT));
  return identities.find((identity) => identity.identityId === identityId) ?? null;
}

export function deleteStoredCustomAvatarIdentity(identityId: string): boolean {
  if (typeof window === "undefined") return false;
  const catalog = readStoredCustomAvatarCatalog();
  const identities = catalog.identities.filter((identity) => identity.identityId !== identityId);
  if (identities.length === catalog.identities.length) return false;
  persistCatalog({
    ...catalog,
    identities,
    selectedIdentityId: catalog.selectedIdentityId === identityId
      ? identities.at(-1)?.identityId ?? ""
      : catalog.selectedIdentityId,
  });
  window.dispatchEvent(new CustomEvent(AVATAR_IDENTITY_UPDATED_EVENT));
  return true;
}

export function selectStoredCustomAvatarIdentity(identityId: string): StoredCustomAvatarIdentity | null {
  if (typeof window === "undefined") return null;
  const catalog = readStoredCustomAvatarCatalog();
  const selected = catalog.identities.find((identity) => identity.identityId === identityId);
  if (!selected) return null;
  persistCatalog({ ...catalog, selectedIdentityId: identityId });
  window.dispatchEvent(new CustomEvent(AVATAR_IDENTITY_UPDATED_EVENT));
  return selected;
}

function readStoredCustomAvatarCatalog(): StoredCustomAvatarCatalog {
  if (typeof window === "undefined") return { version: 2, selectedIdentityId: "", identities: [] };
  try {
    const value = JSON.parse(window.localStorage.getItem(CUSTOM_AVATAR_IDENTITY_STORAGE_KEY) ?? "null") as unknown;
    if (isCatalog(value)) {
      const identities = value.identities.filter(isStoredIdentity).slice(-MAX_LOCAL_IDENTITIES);
      const selectedIdentityId = identities.some((identity) => identity.identityId === value.selectedIdentityId)
        ? value.selectedIdentityId
        : identities.at(-1)?.identityId ?? "";
      return { version: 2, selectedIdentityId, identities };
    }
    const legacy = normalizeLegacyIdentity(value);
    if (!legacy) return { version: 2, selectedIdentityId: "", identities: [] };
    const migrated = { version: 2 as const, selectedIdentityId: legacy.identityId, identities: [legacy] };
    persistCatalog(migrated);
    return migrated;
  } catch {
    return { version: 2, selectedIdentityId: "", identities: [] };
  }
}

export async function storeCustomAvatarIdentity(file: File): Promise<StoredCustomAvatarIdentity> {
  if (!file.type.startsWith("image/")) throw new Error("请选择图片文件");
  if (file.size > 10 * 1024 * 1024) throw new Error("身份图片不能超过 10MB");
  const bitmap = await createImageBitmap(file);
  const maxSide = 1024;
  const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(bitmap.width * scale));
  canvas.height = Math.max(1, Math.round(bitmap.height * scale));
  const context = canvas.getContext("2d");
  if (!context) throw new Error("浏览器无法处理这张图片");
  context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  const dataUrl = canvas.toDataURL("image/jpeg", 0.86);
  const identity = {
    identityId: `custom-${crypto.randomUUID()}`,
    name: file.name,
    dataUrl,
    sourceSha256: await sha256DataUrl(dataUrl),
    updatedAt: new Date().toISOString(),
  };
  const catalog = readStoredCustomAvatarCatalog();
  persistCatalog({
    version: 2,
    selectedIdentityId: identity.identityId,
    identities: [...catalog.identities.filter((item) => item.identityId !== identity.identityId), identity]
      .slice(-MAX_LOCAL_IDENTITIES),
  });
  window.dispatchEvent(new CustomEvent(AVATAR_IDENTITY_UPDATED_EVENT));
  return identity;
}

function persistCatalog(catalog: StoredCustomAvatarCatalog) {
  window.localStorage.setItem(CUSTOM_AVATAR_IDENTITY_STORAGE_KEY, JSON.stringify(catalog));
}

function isCatalog(value: unknown): value is StoredCustomAvatarCatalog {
  return Boolean(value)
    && typeof value === "object"
    && (value as Partial<StoredCustomAvatarCatalog>).version === 2
    && Array.isArray((value as Partial<StoredCustomAvatarCatalog>).identities)
    && typeof (value as Partial<StoredCustomAvatarCatalog>).selectedIdentityId === "string";
}

function isStoredIdentity(value: unknown): value is StoredCustomAvatarIdentity {
  if (!value || typeof value !== "object") return false;
  const identity = value as Partial<StoredCustomAvatarIdentity>;
  return validCustomIdentityId(identity.identityId)
    && typeof identity.name === "string"
    && typeof identity.dataUrl === "string"
    && identity.dataUrl.startsWith("data:image/")
    && typeof identity.sourceSha256 === "string"
    && typeof identity.updatedAt === "string";
}

function normalizeLegacyIdentity(value: unknown): StoredCustomAvatarIdentity | null {
  if (!value || typeof value !== "object") return null;
  const identity = value as Partial<StoredCustomAvatarIdentity>;
  if (typeof identity.name !== "string"
    || typeof identity.dataUrl !== "string"
    || !identity.dataUrl.startsWith("data:image/")
    || typeof identity.updatedAt !== "string") return null;
  return {
    identityId: validCustomIdentityId(identity.identityId)
      ? identity.identityId
      : `custom-${crypto.randomUUID()}`,
    name: identity.name,
    dataUrl: identity.dataUrl,
    sourceSha256: typeof identity.sourceSha256 === "string" && identity.sourceSha256
      ? identity.sourceSha256
      : "legacy-unverified",
    updatedAt: identity.updatedAt,
  };
}

function validCustomIdentityId(value: unknown): value is string {
  return typeof value === "string"
    && /^custom-[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(value);
}

async function sha256DataUrl(dataUrl: string) {
  const encoded = dataUrl.split(",", 2)[1];
  if (!encoded) throw new Error("身份图片编码失败");
  const binary = atob(encoded);
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

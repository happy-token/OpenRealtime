export const MOTION_ASSET_METADATA_STORAGE_KEY = "openrealtime-motion-asset-metadata-v1";

type MotionAssetMetadata = {
  version: 1;
  displayNames: Record<string, string>;
  hiddenIds: string[];
  hiddenIdentityIds: string[];
};

const EMPTY_METADATA: MotionAssetMetadata = { version: 1, displayNames: {}, hiddenIds: [], hiddenIdentityIds: [] };
const VALID_ID = /^[a-zA-Z0-9][a-zA-Z0-9._:-]{1,127}$/;
const MAX_NAME_LENGTH = 48;

export function readMotionAssetMetadata(): MotionAssetMetadata {
  if (typeof window === "undefined") return EMPTY_METADATA;
  try {
    const value = JSON.parse(window.localStorage.getItem(MOTION_ASSET_METADATA_STORAGE_KEY) ?? "null") as Partial<MotionAssetMetadata> | null;
    if (!value || value.version !== 1) return EMPTY_METADATA;
    const displayNames = Object.fromEntries(Object.entries(value.displayNames ?? {}).filter(([id, name]) => (
      VALID_ID.test(id) && typeof name === "string" && Boolean(name.trim())
    )));
    const hiddenIds = Array.isArray(value.hiddenIds)
      ? value.hiddenIds.filter((id): id is string => typeof id === "string" && VALID_ID.test(id))
      : [];
    const hiddenIdentityIds = Array.isArray(value.hiddenIdentityIds)
      ? value.hiddenIdentityIds.filter((id): id is string => typeof id === "string" && VALID_ID.test(id))
      : [];
    return {
      version: 1,
      displayNames,
      hiddenIds: [...new Set(hiddenIds)],
      hiddenIdentityIds: [...new Set(hiddenIdentityIds)],
    };
  } catch {
    return EMPTY_METADATA;
  }
}

export function storeMotionAssetDisplayName(assetId: string, requestedName: string): string {
  if (typeof window === "undefined") return requestedName.trim();
  if (!VALID_ID.test(assetId)) throw new Error("动作资产 ID 无效");
  const metadata = readMotionAssetMetadata();
  const base = requestedName.trim().slice(0, MAX_NAME_LENGTH) || "未命名动作";
  const used = new Set(Object.entries(metadata.displayNames)
    .filter(([id]) => id !== assetId)
    .map(([, name]) => name.toLocaleLowerCase()));
  let name = base;
  let suffix = 2;
  while (used.has(name.toLocaleLowerCase())) {
    const ending = ` ${suffix}`;
    name = `${base.slice(0, MAX_NAME_LENGTH - ending.length)}${ending}`;
    suffix += 1;
  }
  persistMotionMetadata({
    ...metadata,
    displayNames: { ...metadata.displayNames, [assetId]: name },
  });
  return name;
}

export function hideMotionAsset(assetId: string): boolean {
  if (typeof window === "undefined" || !VALID_ID.test(assetId)) return false;
  const metadata = readMotionAssetMetadata();
  if (metadata.hiddenIds.includes(assetId)) return false;
  persistMotionMetadata({ ...metadata, hiddenIds: [...metadata.hiddenIds, assetId] });
  return true;
}

export function hideIdentityAsset(assetId: string): boolean {
  if (typeof window === "undefined" || !VALID_ID.test(assetId)) return false;
  const metadata = readMotionAssetMetadata();
  if (metadata.hiddenIdentityIds.includes(assetId)) return false;
  persistMotionMetadata({
    ...metadata,
    hiddenIdentityIds: [...metadata.hiddenIdentityIds, assetId],
  });
  return true;
}

function persistMotionMetadata(metadata: MotionAssetMetadata) {
  window.localStorage.setItem(MOTION_ASSET_METADATA_STORAGE_KEY, JSON.stringify(metadata));
}

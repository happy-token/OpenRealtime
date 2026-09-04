import type { StoredCustomAvatarIdentity } from "./avatar-identity-sync";

export type WorkbenchIdentityAsset = {
  id: string;
  name: string;
  width?: number;
  height?: number;
  previewImageUrl: string;
  sourceImageUrl: string;
  origin: string;
  category: "saved" | "reference";
};

export type WorkbenchIdentityCategory = "all" | WorkbenchIdentityAsset["category"];

export function mergeWorkbenchIdentityAssets(
  builtInAssets: readonly WorkbenchIdentityAsset[],
  customIdentities: readonly StoredCustomAvatarIdentity[],
): WorkbenchIdentityAsset[] {
  return [
    ...builtInAssets,
    ...customIdentities.map((identity) => ({
      id: identity.identityId,
      name: identity.name,
      previewImageUrl: identity.dataUrl,
      sourceImageUrl: identity.dataUrl,
      origin: "授权上传",
      category: "saved" as const,
    })),
  ];
}

export function filterWorkbenchIdentityAssets(
  assets: readonly WorkbenchIdentityAsset[],
  category: WorkbenchIdentityCategory,
  query: string,
) {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  return assets.filter((asset) => (
    (category === "all" || asset.category === category)
    && (!normalizedQuery || `${asset.name} ${asset.origin}`.toLocaleLowerCase().includes(normalizedQuery))
  ));
}

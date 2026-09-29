import type { AnamHostedAvatar } from "./anam-avatars";
import { buildAvatarCatalog, type AvatarAction, type AvatarAsset, type AvatarCatalogRecords } from "./avatar-catalog";
import { fetchOwnedAvatars, fetchPersonalAvatars } from "./avatar-catalog-client";
import type { OwnedAvatarRecord } from "./avatar-records";
import { BUILTIN_AVATAR_ACTIONS } from "./builtin-avatar-actions";
import { readJsonResponse } from "./http-json-response";
import { INTERNAL_AVATAR_PRESET_IDS, readInternalAvatarPresetCatalog } from "./internal-avatar-presets";

const initialRecords: AvatarCatalogRecords = {
  avatars: [],
  actions: [],
  realtime_bindings: [],
};

const internalPresetIdSet = new Set<string>(INTERNAL_AVATAR_PRESET_IDS);

export function isSegmentedAvatarAsset(
  avatar: AvatarAsset,
  internalPresetIds: ReadonlySet<string> = internalPresetIdSet,
) {
  return !avatar.deletedAt && (
    internalPresetIds.has(avatar.avatarId)
    || (avatar.source.kind === "owned" && Boolean(avatar.ownerId) && !avatar.realtimeBinding)
  );
}

export function collapseDuplicateOwnedAvatars(
  avatars: readonly OwnedAvatarRecord[],
): OwnedAvatarRecord[] {
  const canonicalByIdentity = new Map<string, OwnedAvatarRecord>();
  for (const avatar of avatars) {
    const identityKey = avatar.deleted_at
      ? `deleted:${avatar.avatar_id}`
      : `active:${normalizeAvatarDisplayName(avatar.display_name)}`;
    const current = canonicalByIdentity.get(identityKey);
    if (!current || preferOwnedAvatar(avatar, current)) {
      canonicalByIdentity.set(identityKey, avatar);
    }
  }
  return [...canonicalByIdentity.values()];
}

export function loadInternalPresetAvatars(
  options: { includeLocal?: boolean } = {},
): AvatarAsset[] {
  const internalCatalog = readInternalAvatarPresetCatalog(options);
  return buildAvatarCatalog({
    avatars: internalCatalog.identities.map((identity) => ({
      avatar_id: identity.id,
      display_name: identity.name,
      owner_id: null,
      visibility: "shared" as const,
      source_image_url: identity.sourceImageUrl,
    })),
    actions: internalCatalog.motions.map((motion) => ({
      avatar_action_id: motion.id,
      avatar_id: motion.visualIdentityId,
      display_name: motion.name,
      state: "available" as const,
      video_url: motion.videoUrl,
      pending_model_count: 0,
    })),
    realtime_bindings: [],
  });
}

export async function loadCurrentAvatarCatalog(
  signal?: AbortSignal,
  options: {
    includeHostedAvatars?: boolean;
    includeOwnedBuiltinActions?: boolean;
    ownedAvatars?: Promise<OwnedAvatarRecord[]>;
    personalAvatars?: Promise<OwnedAvatarRecord[]>;
  } = {},
): Promise<AvatarAsset[]> {
  const includeHostedAvatars = options.includeHostedAvatars ?? true;
  const includeOwnedBuiltinActions = options.includeOwnedBuiltinActions ?? false;
  const [ownedResult, personalResult, anamResult] = await Promise.allSettled([
    options.ownedAvatars ?? fetchOwnedAvatars(signal),
    options.personalAvatars ?? fetchPersonalAvatars(signal),
    includeHostedAvatars
      ? fetch("/api/anam/avatars", { cache: "no-store", signal }).then(async (response) => {
        const payload = await readJsonResponse<{ avatars?: AnamHostedAvatar[] }>(response, "Anam 目录读取失败");
        if (!response.ok) throw new Error("Anam 目录读取失败");
        return payload.avatars ?? [];
      })
      : Promise.resolve<AnamHostedAvatar[]>([]),
  ]);
  const adminOwned = ownedResult.status === "fulfilled"
    ? collapseDuplicateOwnedAvatars(ownedResult.value)
    : [];
  const personalOwned = personalResult.status === "fulfilled" ? personalResult.value : [];
  const owned = [...adminOwned, ...personalOwned];
  const internalCatalog = readInternalAvatarPresetCatalog();
  const records: AvatarCatalogRecords = {
    avatars: [
      ...internalCatalog.identities.map((identity) => ({
        avatar_id: identity.id,
        display_name: identity.name,
        owner_id: null,
        visibility: "shared" as const,
        source_image_url: identity.sourceImageUrl,
      })),
      ...initialRecords.avatars,
      ...owned.filter((avatar) => !internalPresetIdSet.has(avatar.avatar_id)).map((avatar) => ({
        avatar_id: avatar.avatar_id,
        display_name: avatar.display_name,
        owner_id: "local-user",
        visibility: "private" as const,
        source_image_url: avatar.source_image_url,
        deleted_at: avatar.deleted_at,
      })),
    ],
    actions: [
      ...internalCatalog.motions.map((motion) => ({
        avatar_action_id: motion.id,
        avatar_id: motion.visualIdentityId,
        display_name: motion.name,
        state: "available" as const,
        video_url: motion.videoUrl,
        pending_model_count: 0,
      })),
      ...owned.flatMap((avatar) => avatar.actions.map((action) => ({
        avatar_action_id: action.avatar_action_id,
        avatar_id: avatar.avatar_id,
        display_name: action.display_name,
        state: action.pending_model_count ? "processing" as const : "available" as const,
        video_url: action.video_url,
        pending_model_count: action.pending_model_count,
        deleted_at: action.deleted_at,
      }))),
    ],
    realtime_bindings: owned.flatMap((avatar) => avatar.realtime_binding ? [avatar.realtime_binding] : []),
  };
  if (anamResult.status === "fulfilled") {
    for (const anam of anamResult.value) {
      if (records.avatars.some((avatar) => avatar.avatar_id === `anam-${anam.id}`)) continue;
      records.avatars.push({
        avatar_id: `anam-${anam.id}`,
        display_name: anam.displayName,
        owner_id: anam.origin === "personal" ? "local-user" : null,
        visibility: anam.origin === "personal" ? "private" : "shared",
        source_image_url: null,
        provider_preview_url: anam.imageUrl,
      });
      records.realtime_bindings.push({
        avatar_id: `anam-${anam.id}`,
        provider_avatar_id: anam.id,
        provider: "anam",
        avatar_model: anam.activeVersion,
        state: "accepted",
        preview_video_url: anam.videoUrl,
      });
    }
  }
  const catalog = buildAvatarCatalog(records).map(avatar => avatar.avatarId.startsWith("avatar-personal-")
    ? { ...avatar, canCreateActions: false }
    : avatar);
  return includeOwnedBuiltinActions ? mergeOwnedBuiltinAvatarActions(catalog) : catalog;
}

export function mergeOwnedBuiltinAvatarActions(avatars: readonly AvatarAsset[]): AvatarAsset[] {
  return avatars.map((avatar) => {
    if (internalPresetIdSet.has(avatar.avatarId)) return avatar;
    const savedActionNames = new Set(avatar.actions
      .map((action) => normalizeAvatarDisplayName(action.displayName)));
    const missingBuiltinActions = BUILTIN_AVATAR_ACTIONS
      .filter((action) => (
        action.avatarId === avatar.avatarId
        && !savedActionNames.has(normalizeAvatarDisplayName(action.name))
      ))
      .map((action) => ({
        avatarActionId: action.id,
        displayName: action.name,
        state: "available" as const,
        videoUrl: action.videoUrl,
        pendingModelCount: 0,
      }));
    if (!missingBuiltinActions.length) return avatar;
    const mergedActions = [...avatar.actions, ...missingBuiltinActions];
    const dedupedActions: AvatarAction[] = [];
    const seenActionNames = new Set<string>();
    for (const action of mergedActions) {
      const nameKey = normalizeAvatarDisplayName(action.displayName);
      if (seenActionNames.has(nameKey)) continue;
      seenActionNames.add(nameKey);
      dedupedActions.push(action);
    }
    return { ...avatar, actions: dedupedActions };
  });
}

function normalizeAvatarDisplayName(displayName: string) {
  return displayName.normalize("NFKC").trim().toLocaleLowerCase();
}

function preferOwnedAvatar(candidate: OwnedAvatarRecord, current: OwnedAvatarRecord) {
  const candidateCapabilityCount = Number(Boolean(candidate.realtime_binding))
    + candidate.actions.filter((action) => !action.deleted_at).length;
  const currentCapabilityCount = Number(Boolean(current.realtime_binding))
    + current.actions.filter((action) => !action.deleted_at).length;
  if (candidateCapabilityCount !== currentCapabilityCount) {
    return candidateCapabilityCount > currentCapabilityCount;
  }
  return candidate.updated_at > current.updated_at;
}

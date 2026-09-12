import { withAvatarCatalogLock } from "./avatar-catalog-lock";
import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, unlink, writeFile } from "node:fs/promises";
import path from "node:path";
import type { AvatarRealtimeBindingRecord } from "./avatar-catalog";
import type { AvatarTalkingVariant, OwnedAvatarActionRecord, OwnedAvatarRecord } from "./avatar-records";
import { isInternalAvatarPresetId } from "./internal-avatar-ids";
import { hasMatchingImageSignature } from "./media-signatures";

type StoredAvatar = Omit<OwnedAvatarRecord, "source_image_url"> & {
  source_image_media_type: string;
  source_image_version?: string;
};

const IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);
const MAX_IMAGE_BYTES = 4_500_000;
const AVATAR_ID = /^avatar-[A-Za-z0-9-]{3,80}$/;
const ACTION_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;

export async function listOwnedAvatars(root = repositoryRoot()) {
  return withAvatarCatalogLock(root, async () => {
    const records = await readCatalog(root);
    const purged = purgeExpired(records);
    if (purged.changed) {
      await writeCatalog(root, purged.records);
      await Promise.all(purged.removedAvatars.map(async (avatar) => {
        try {
          await unlink(storedImagePath(root, avatar));
        } catch (error) {
          if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
        }
      }));
    }
    return purged.records.map(publicRecord);
  });
}

export async function findOwnedAvatar(avatarId: string, root = repositoryRoot()) {
  validateAvatarId(avatarId);
  const records = await readCatalog(root);
  const record = records.find((avatar) => avatar.avatar_id === avatarId);
  return record ? publicRecord(record) : null;
}

export async function createOwnedAvatar(
  input: { displayName: string; sourceImageDataUrl: string; avatarId?: string },
  root = repositoryRoot(),
) {
  return withAvatarCatalogLock(root, async () => {
    const displayName = normalizeName(input.displayName, "请填写 Avatar 名称");
    const avatarId = input.avatarId?.trim() || `avatar-${randomUUID()}`;
    validateAvatarId(avatarId);
    const records = await readCatalog(root);
    const existing = records.find((avatar) => avatar.avatar_id === avatarId);
    if (existing) {
      if (isInternalAvatarPresetId(avatarId)) return publicRecord(existing);
      throw new Error("avatar_id 已存在");
    }
    const image = decodeImage(input.sourceImageDataUrl);
    const now = new Date().toISOString();
    const imageVersion = randomUUID();
    const record: StoredAvatar = {
      avatar_id: avatarId,
      display_name: displayName,
      source_image_media_type: image.mediaType,
      source_image_version: imageVersion,
      created_at: now,
      updated_at: now,
      deleted_at: null,
      realtime_binding: null,
      actions: [],
    };
    await mkdir(imagesDir(root), { recursive: true });
    const target = versionedImagePath(root, avatarId, imageVersion);
    await writeFile(target, image.bytes, { flag: "wx", mode: 0o600 });
    try {
      await writeCatalog(root, [...records, record]);
    } catch (error) {
      await unlink(target).catch(() => undefined);
      throw error;
    }
    return publicRecord(record);
  });
}

export async function updateOwnedAvatar(
  avatarId: string,
  update: { deletedAt?: string | null; realtimeBinding?: AvatarRealtimeBindingRecord | null; displayName?: string },
  root = repositoryRoot(),
) {
  validateAvatarId(avatarId);
  return withAvatarCatalogLock(root, async () => {
    const records = await readCatalog(root);
    const current = records.find((avatar) => avatar.avatar_id === avatarId);
    if (!current) throw new Error("找不到这个 Avatar");
    const next: StoredAvatar = {
      ...current,
      updated_at: new Date().toISOString(),
      ...(Object.hasOwn(update, "deletedAt") ? { deleted_at: update.deletedAt ?? null } : {}),
      ...(Object.hasOwn(update, "realtimeBinding") ? { realtime_binding: update.realtimeBinding ?? null } : {}),
      ...(typeof update.displayName === "string" ? { display_name: normalizeName(update.displayName, "请填写 Avatar 名称") } : {}),
    };
    await writeCatalog(root, records.map((avatar) => avatar.avatar_id === avatarId ? next : avatar));
    return publicRecord(next);
  });
}

export async function replaceOwnedAvatarSourceImage(
  avatarId: string,
  input: { sourceImageDataUrl: string; trashActions: boolean },
  root = repositoryRoot(),
) {
  validateAvatarId(avatarId);
  return withAvatarCatalogLock(root, async () => {
    const records = await readCatalog(root);
    const current = records.find((avatar) => avatar.avatar_id === avatarId);
    if (!current) throw new Error("找不到这个 Avatar");
    const image = decodeImage(input.sourceImageDataUrl);
    const replacedAt = new Date().toISOString();
    const imageVersion = randomUUID();
    const next: StoredAvatar = {
      ...current,
      source_image_media_type: image.mediaType,
      source_image_version: imageVersion,
      updated_at: replacedAt,
      realtime_binding: null,
      actions: input.trashActions
        ? current.actions.map((action) => action.deleted_at ? action : { ...action, deleted_at: replacedAt })
        : current.actions,
    };
    await mkdir(imagesDir(root), { recursive: true });
    const target = versionedImagePath(root, avatarId, imageVersion);
    await writeFile(target, image.bytes, { flag: "wx", mode: 0o600 });
    try {
      await writeCatalog(root, records.map((avatar) => avatar.avatar_id === avatarId ? next : avatar));
    } catch (error) {
      await unlink(target).catch(() => undefined);
      throw error;
    }
    try {
      await unlink(storedImagePath(root, current));
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
        console.warn(`Failed to remove superseded Avatar image for ${avatarId}`, error);
      }
    }
    return publicRecord(next);
  });
}

export async function appendOwnedAvatarAction(
  avatarId: string,
  input: Pick<OwnedAvatarActionRecord, "avatar_action_id" | "display_name" | "video_url"> & { pending_model_count?: number },
  root = repositoryRoot(),
) {
  validateAvatarId(avatarId);
  if (!ACTION_ID.test(input.avatar_action_id)) throw new Error("avatar_action_id 无效");
  return withAvatarCatalogLock(root, async () => {
    const records = await readCatalog(root);
    const current = records.find((avatar) => avatar.avatar_id === avatarId);
    if (!current) throw new Error("找不到要添加动作的 Avatar");
    const action: OwnedAvatarActionRecord = {
      avatar_action_id: input.avatar_action_id,
      display_name: normalizeName(input.display_name, "请填写动作名称"),
      video_url: input.video_url,
      pending_model_count: Math.max(0, input.pending_model_count ?? 0),
      created_at: new Date().toISOString(),
      deleted_at: null,
    };
    const next = {
      ...current,
      updated_at: new Date().toISOString(),
      actions: [...current.actions.filter((item) => item.avatar_action_id !== action.avatar_action_id), action],
    };
    await writeCatalog(root, records.map((avatar) => avatar.avatar_id === avatarId ? next : avatar));
    return action;
  });
}

export async function updateOwnedAvatarAction(
  avatarId: string,
  avatarActionId: string,
  update: { deletedAt?: string | null; pendingModelCount?: number; displayName?: string },
  root = repositoryRoot(),
) {
  validateAvatarId(avatarId);
  if (!ACTION_ID.test(avatarActionId)) throw new Error("avatar_action_id 无效");
  return withAvatarCatalogLock(root, async () => {
    const records = await readCatalog(root);
    const current = records.find((avatar) => avatar.avatar_id === avatarId);
    if (!current) throw new Error("找不到这个 Avatar");
    let updated: OwnedAvatarActionRecord | null = null;
    const actions = current.actions.map((action) => {
      if (action.avatar_action_id !== avatarActionId) return action;
      updated = {
        ...action,
        ...(Object.hasOwn(update, "deletedAt") ? { deleted_at: update.deletedAt ?? null } : {}),
        ...(typeof update.pendingModelCount === "number" ? { pending_model_count: Math.max(0, update.pendingModelCount) } : {}),
        ...(typeof update.displayName === "string" ? { display_name: normalizeName(update.displayName, "请填写动作名称") } : {}),
      };
      return updated;
    });
    if (!updated) throw new Error("找不到这个 Avatar 动作");
    await writeCatalog(root, records.map((avatar) => avatar.avatar_id === avatarId
      ? { ...avatar, updated_at: new Date().toISOString(), actions }
      : avatar));
    return updated;
  });
}

export async function attachTalkingVariant(avatarId: string, actionId: string, variant: AvatarTalkingVariant, root = repositoryRoot()) {
  validateAvatarId(avatarId);
  if (!ACTION_ID.test(actionId) || !isTalkingVariant(variant)) throw new Error("讲话变体参数无效");
  return withAvatarCatalogLock(root, async () => {
    const records = await readCatalog(root);
    const avatar = records.find(record => record.avatar_id === avatarId && !record.deleted_at);
    const action = avatar?.actions.find(record => record.avatar_action_id === actionId && !record.deleted_at);
    if (!avatar || !action) throw new Error("找不到基础动作");
    if (action.video_url !== variant.source_video_url) throw new Error("讲话变体底片不匹配");
    const updated = { ...action, talking_variants: [...(action.talking_variants || []).filter(item => item.id !== variant.id && item.method !== variant.method), variant] };
    await writeCatalog(root, records.map(record => record === avatar ? { ...avatar, updated_at: new Date().toISOString(), actions: avatar.actions.map(item => item === action ? updated : item) } : record));
    return updated;
  });
}

function isTalkingVariant(value: unknown): value is AvatarTalkingVariant {
  if (!value || typeof value !== "object") return false;
  const item = value as AvatarTalkingVariant;
  return typeof item.id === "string" && /^[a-z0-9-]{1,100}$/.test(item.id)
    && typeof item.display_name === "string" && item.display_name.length > 0 && item.display_name.length <= 100
    && (item.method === "wav2lip" || item.method === "minimax" || item.method === "musetalk")
    && typeof item.source_video_url === "string"
    && item.video_url === `/digital-human/talking-variants/${item.id}.mp4`
    && (item.processing === "mouth-only" || (item.processing === "original" && (item.method === "minimax" || item.method === "musetalk"))) && item.validation === "pending";
}

export async function readOwnedAvatarImage(avatarId: string, root = repositoryRoot()) {
  validateAvatarId(avatarId);
  return withAvatarCatalogLock(root, async () => {
    const record = (await readCatalog(root)).find((avatar) => avatar.avatar_id === avatarId);
    if (!record) return null;
    return { bytes: await readFile(storedImagePath(root, record)), mediaType: record.source_image_media_type };
  });
}

function publicRecord(record: StoredAvatar): OwnedAvatarRecord {
  return {
    avatar_id: record.avatar_id,
    display_name: record.display_name,
    source_image_url: `/api/avatars/${encodeURIComponent(record.avatar_id)}/image`,
    created_at: record.created_at,
    updated_at: record.updated_at,
    deleted_at: record.deleted_at,
    realtime_binding: record.realtime_binding,
    actions: record.actions,
  };
}

function repositoryRoot() {
  return path.resolve(process.env.AVATAR_CATALOG_DIR?.trim() || path.join(process.cwd(), ".openrealtime", "avatar-catalog"));
}

function catalogPath(root: string) { return path.join(root, "catalog.json"); }
function imagesDir(root: string) { return path.join(root, "images"); }
function legacyImagePath(root: string, avatarId: string) { return path.join(imagesDir(root), `${avatarId}.image`); }
function versionedImagePath(root: string, avatarId: string, version: string) { return path.join(imagesDir(root), `${avatarId}.${version}.image`); }
function storedImagePath(root: string, avatar: StoredAvatar) {
  return avatar.source_image_version
    ? versionedImagePath(root, avatar.avatar_id, avatar.source_image_version)
    : legacyImagePath(root, avatar.avatar_id);
}

async function readCatalog(root: string): Promise<StoredAvatar[]> {
  try {
    const value = JSON.parse(await readFile(catalogPath(root), "utf8")) as unknown;
    if (!Array.isArray(value) || !value.every(isStoredAvatar)) {
      throw new Error("Avatar 目录结构异常，已停止读写以保护现有资产");
    }
    return value;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw error;
  }
}

async function writeCatalog(root: string, records: StoredAvatar[]) {
  await mkdir(root, { recursive: true });
  const temporary = path.join(root, `catalog.${randomUUID()}.tmp`);
  await writeFile(temporary, JSON.stringify(records, null, 2), { flag: "wx", mode: 0o600 });
  await rename(temporary, catalogPath(root));
}

function decodeImage(value: string) {
  const match = /^data:(image\/(?:jpeg|png|webp));base64,([A-Za-z0-9+/=]+)$/.exec(value);
  if (!match || !IMAGE_TYPES.has(match[1])) throw new Error("Avatar 源图格式无效");
  const bytes = Buffer.from(match[2], "base64");
  if (!bytes.length || bytes.length > MAX_IMAGE_BYTES) throw new Error("Avatar 源图不能超过 4.5MB");
  if (!hasMatchingImageSignature(match[1], bytes)) throw new Error("Avatar 源图内容与格式不匹配");
  return { mediaType: match[1], bytes };
}

function purgeExpired(records: StoredAvatar[]) {
  const cutoff = Date.now() - 30 * 24 * 60 * 60 * 1_000;
  const removedAvatars: StoredAvatar[] = [];
  let changed = false;
  const retained = records.flatMap((avatar) => {
    if (avatar.deleted_at && new Date(avatar.deleted_at).valueOf() <= cutoff) {
      removedAvatars.push(avatar);
      changed = true;
      return [];
    }
    const actions = avatar.actions.filter((action) => (
      !action.deleted_at || new Date(action.deleted_at).valueOf() > cutoff
    ));
    if (actions.length !== avatar.actions.length) changed = true;
    return [{ ...avatar, actions }];
  });
  return { records: retained, removedAvatars, changed };
}

function validateAvatarId(value: string) {
  if (!AVATAR_ID.test(value) && !isInternalAvatarPresetId(value)) throw new Error("avatar_id 无效");
}

function normalizeName(value: string, emptyMessage: string) {
  const name = value.trim().slice(0, 50);
  if (!name) throw new Error(emptyMessage);
  return name;
}

function isStoredAvatar(value: unknown): value is StoredAvatar {
  if (!value || typeof value !== "object") return false;
  const avatar = value as Partial<StoredAvatar>;
  return typeof avatar.avatar_id === "string"
    && (AVATAR_ID.test(avatar.avatar_id) || isInternalAvatarPresetId(avatar.avatar_id))
    && typeof avatar.display_name === "string"
    && typeof avatar.source_image_media_type === "string"
    && (avatar.source_image_version === undefined || /^[A-Za-z0-9-]{1,80}$/.test(avatar.source_image_version))
    && typeof avatar.created_at === "string"
    && typeof avatar.updated_at === "string"
    && (avatar.deleted_at === null || typeof avatar.deleted_at === "string")
    && IMAGE_TYPES.has(avatar.source_image_media_type)
    && Array.isArray(avatar.actions)
    && avatar.actions.every(isStoredAction)
    && (avatar.realtime_binding === null || isStoredRealtimeBinding(avatar.realtime_binding));
}

function isStoredAction(value: unknown): value is OwnedAvatarActionRecord {
  if (!value || typeof value !== "object") return false;
  const action = value as Partial<OwnedAvatarActionRecord>;
  return typeof action.avatar_action_id === "string"
    && ACTION_ID.test(action.avatar_action_id)
    && typeof action.display_name === "string"
    && (action.video_url === null || typeof action.video_url === "string")
    && typeof action.pending_model_count === "number"
    && typeof action.created_at === "string"
    && (action.deleted_at === null || typeof action.deleted_at === "string");
}

function isStoredRealtimeBinding(value: unknown): value is AvatarRealtimeBindingRecord {
  if (!value || typeof value !== "object") return false;
  const binding = value as Partial<AvatarRealtimeBindingRecord>;
  return typeof binding.avatar_id === "string"
    && binding.provider === "anam"
    && typeof binding.provider_avatar_id === "string"
    && typeof binding.avatar_model === "string"
    && binding.state === "accepted"
    && (binding.preview_video_url == null || typeof binding.preview_video_url === "string");
}

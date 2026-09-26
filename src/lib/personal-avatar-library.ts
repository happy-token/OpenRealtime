import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, stat, unlink, writeFile } from "node:fs/promises";
import path from "node:path";
import { withAvatarCatalogLock } from "./avatar-catalog-lock";
import { hasMatchingImageSignature } from "./media-signatures";
import { findPersonalMotion, personalLibraryOwnerDir } from "./personal-motion-library";
import type { AvatarTalkingVariant, OwnedAvatarActionRecord, OwnedAvatarRecord } from "./avatar-records";
import type { WebUser } from "./user-session";

type PersonalAvatar = {
  id: string;
  name: string;
  imageType: "image/jpeg" | "image/png" | "image/webp";
  createdAt: string;
  updatedAt: string;
  deletedAt: string | null;
  actions: OwnedAvatarActionRecord[];
};

const AVATAR_ID = /^avatar-personal-[a-f0-9-]{36}$/;
const MAX_IMAGE_BYTES = 4_500_000;

function avatarDir(user: WebUser) { return path.join(personalLibraryOwnerDir(user), "avatars"); }
function catalogFile(dir: string) { return path.join(dir, "catalog.json"); }
function imageFile(dir: string, id: string) { return path.join(dir, `${id}.image`); }

async function readCatalog(dir: string): Promise<PersonalAvatar[]> {
  try {
    const records = JSON.parse(await readFile(catalogFile(dir), "utf8")) as unknown;
    if (!Array.isArray(records) || !records.every(isPersonalAvatar)) throw new Error("个人 Avatar 目录结构异常");
    return records;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw error;
  }
}

async function writeCatalog(dir: string, records: PersonalAvatar[]) {
  await mkdir(dir, { recursive: true, mode: 0o700 });
  const temporary = path.join(dir, `catalog.${randomUUID()}.tmp`);
  await writeFile(temporary, JSON.stringify(records, null, 2), { flag: "wx", mode: 0o600 });
  await rename(temporary, catalogFile(dir));
}

function publicRecord(avatar: PersonalAvatar): OwnedAvatarRecord {
  return {
    avatar_id: avatar.id,
    display_name: avatar.name,
    source_image_url: `/api/user/avatars/${avatar.id}/image?v=${encodeURIComponent(avatar.createdAt)}`,
    created_at: avatar.createdAt,
    updated_at: avatar.updatedAt,
    deleted_at: avatar.deletedAt,
    realtime_binding: null,
    actions: avatar.actions,
  };
}

export async function listPersonalAvatars(user: WebUser) {
  return (await readCatalog(avatarDir(user))).map(publicRecord);
}

export async function findPersonalAvatar(user: WebUser, id: string) {
  if (!AVATAR_ID.test(id)) return null;
  return (await readCatalog(avatarDir(user))).find(avatar => avatar.id === id) ?? null;
}

export async function createPersonalAvatar(user: WebUser, name: string, imageType: string, bytes: Uint8Array) {
  if (!name.trim() || name.trim().length > 50) throw new Error("请填写 50 字以内的数字人名称");
  if (imageType !== "image/jpeg" && imageType !== "image/png" && imageType !== "image/webp") throw new Error("图片格式无效");
  if (!bytes.byteLength || bytes.byteLength > MAX_IMAGE_BYTES || !hasMatchingImageSignature(imageType, bytes)) throw new Error("图片内容无效或超过 4.5MB");
  const dir = avatarDir(user);
  await mkdir(dir, { recursive: true, mode: 0o700 });
  return withAvatarCatalogLock(dir, async () => {
    const records = await readCatalog(dir);
    if (records.filter(record => !record.deletedAt).length >= 50) throw new Error("个人数字人数量已达上限");
    const id = `avatar-personal-${randomUUID()}`;
    const now = new Date().toISOString();
    const avatar: PersonalAvatar = { id, name: name.trim(), imageType, createdAt: now, updatedAt: now, deletedAt: null, actions: [] };
    await writeFile(imageFile(dir, id), bytes, { flag: "wx", mode: 0o600 });
    try {
      await writeCatalog(dir, [...records, avatar]);
    } catch (error) {
      await unlink(imageFile(dir, id)).catch(() => undefined);
      throw error;
    }
    return publicRecord(avatar);
  });
}

export async function attachPersonalMotionToAvatar(user: WebUser, avatarId: string, motionId: string) {
  if (!AVATAR_ID.test(avatarId)) throw new Error("数字人 ID 无效");
  const motion = await findPersonalMotion(user, motionId);
  if (!motion || !await stat(path.join(personalLibraryOwnerDir(user), `${motionId}.mp4`)).catch(() => null)) throw new Error("找不到个人动作素材");
  const dir = avatarDir(user);
  return withAvatarCatalogLock(dir, async () => {
    const records = await readCatalog(dir);
    const avatar = records.find(record => record.id === avatarId && !record.deletedAt);
    if (!avatar) throw new Error("找不到个人数字人");
    const actionId = `motion-${motion.id}`;
    const videoUrl = `/api/user/motion-assets/${motion.id}?preview=1`;
    const existing = avatar.actions.find(action => action.video_url === videoUrl && !action.deleted_at);
    if (existing) return existing;
    const action: OwnedAvatarActionRecord = {
      avatar_action_id: actionId,
      display_name: motion.prompt.trim().slice(0, 50) || "MiniMax 动作",
      video_url: videoUrl,
      pending_model_count: 0,
      created_at: new Date().toISOString(),
      deleted_at: null,
    };
    await writeCatalog(dir, records.map(record => record.id === avatarId
      ? { ...record, updatedAt: new Date().toISOString(), actions: [...record.actions, action] }
      : record));
    return action;
  });
}

export async function attachPersonalTalkingVariant(user: WebUser, avatarId: string, actionId: string, variant: AvatarTalkingVariant) {
  if (!AVATAR_ID.test(avatarId)) throw new Error("数字人 ID 无效");
  const dir = avatarDir(user);
  return withAvatarCatalogLock(dir, async () => {
    const records = await readCatalog(dir);
    const avatar = records.find((record) => record.id === avatarId && !record.deletedAt);
    const action = avatar?.actions.find((item) => item.avatar_action_id === actionId && !item.deleted_at);
    if (!action || !action.video_url || variant.source_video_url !== action.video_url) throw new Error("动作底片已变更，请重新生成口型对齐");
    const updated: OwnedAvatarActionRecord = {
      ...action,
      talking_variants: [...(action.talking_variants ?? []).filter((item) => item.id !== variant.id), variant],
    };
    await writeCatalog(dir, records.map((record) => record.id === avatarId
      ? { ...record, updatedAt: new Date().toISOString(), actions: record.actions.map((item) => item.avatar_action_id === actionId ? updated : item) }
      : record));
    return updated;
  });
}

export async function renamePersonalAvatar(user: WebUser, avatarId: string, displayName: string) {
  if (!AVATAR_ID.test(avatarId)) throw new Error("数字人 ID 无效");
  const name = displayName.trim();
  if (!name || name.length > 50) throw new Error("请填写 50 字以内的数字人名称");
  const dir = avatarDir(user);
  return withAvatarCatalogLock(dir, async () => {
    const records = await readCatalog(dir);
    const avatar = records.find((record) => record.id === avatarId && !record.deletedAt);
    if (!avatar) throw new Error("找不到个人数字人");
    const updated = { ...avatar, name, updatedAt: new Date().toISOString() };
    await writeCatalog(dir, records.map((record) => record.id === avatarId ? updated : record));
    return publicRecord(updated);
  });
}

export async function updatePersonalAvatarAction(
  user: WebUser,
  avatarId: string,
  actionId: string,
  update: { displayName: string },
) {
  if (!AVATAR_ID.test(avatarId)) throw new Error("数字人 ID 无效");
  const displayName = update.displayName.trim();
  if (!displayName || displayName.length > 50) throw new Error("请填写 50 字以内的动作名称");
  const dir = avatarDir(user);
  return withAvatarCatalogLock(dir, async () => {
    const records = await readCatalog(dir);
    const avatar = records.find((record) => record.id === avatarId && !record.deletedAt);
    const action = avatar?.actions.find((record) => record.avatar_action_id === actionId);
    if (!avatar || !action) throw new Error("找不到个人数字人动作");
    const updated: OwnedAvatarActionRecord = {
      ...action,
      display_name: displayName,
    };
    await writeCatalog(dir, records.map((record) => record.id === avatarId
      ? { ...record, updatedAt: new Date().toISOString(), actions: record.actions.map((item) => item.avatar_action_id === actionId ? updated : item) }
      : record));
    return updated;
  });
}

export async function updatePersonalTalkingVariant(
  user: WebUser,
  avatarId: string,
  actionId: string,
  variantId: string,
  update: { displayName: string },
) {
  if (!AVATAR_ID.test(avatarId)) throw new Error("数字人 ID 无效");
  const displayName = update.displayName.trim();
  if (!displayName || displayName.length > 50) throw new Error("请填写 50 字以内的口型对齐名称");
  const dir = avatarDir(user);
  return withAvatarCatalogLock(dir, async () => {
    const records = await readCatalog(dir);
    const avatar = records.find((record) => record.id === avatarId && !record.deletedAt);
    const action = avatar?.actions.find((record) => record.avatar_action_id === actionId && !record.deleted_at);
    const variant = action?.talking_variants?.find((record) => record.id === variantId);
    if (!avatar || !action || !variant) throw new Error("找不到个人口型对齐");
    if (variant.deleted_at) throw new Error("已删除的口型对齐不能改名");
    const updated: OwnedAvatarActionRecord = {
      ...action,
      talking_variants: action.talking_variants?.map((item) => item.id === variantId ? {
        ...item,
        display_name: displayName,
      } : item),
    };
    await writeCatalog(dir, records.map((record) => record.id === avatarId
      ? { ...record, updatedAt: new Date().toISOString(), actions: record.actions.map((item) => item.avatar_action_id === actionId ? updated : item) }
      : record));
    return updated;
  });
}

export async function readPersonalAvatarImage(user: WebUser, id: string) {
  const avatar = await findPersonalAvatar(user, id);
  if (!avatar || avatar.deletedAt) return null;
  return { bytes: await readFile(imageFile(avatarDir(user), id)), mediaType: avatar.imageType, version: avatar.createdAt };
}

function isPersonalAvatar(value: unknown): value is PersonalAvatar {
  if (!value || typeof value !== "object") return false;
  const item = value as Partial<PersonalAvatar>;
  return typeof item.id === "string" && AVATAR_ID.test(item.id)
    && typeof item.name === "string" && item.name.length > 0
    && (item.imageType === "image/jpeg" || item.imageType === "image/png" || item.imageType === "image/webp")
    && typeof item.createdAt === "string" && typeof item.updatedAt === "string"
    && (item.deletedAt === null || typeof item.deletedAt === "string")
    && Array.isArray(item.actions);
}

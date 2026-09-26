import { randomUUID } from "node:crypto";
import { mkdir, readFile, readdir, rename, writeFile } from "node:fs/promises";
import path from "node:path";

import {
  AVATAR_PERSONA_FILENAMES,
  REQUIRED_AVATAR_PERSONA_FILENAMES,
  isBuiltinPersonaId,
  type AvatarPersonaFile,
  type AvatarPersonaProfile,
  type PersonaProfile,
  type PersonaSummary,
} from "./avatar-persona";

const AVATAR_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$/;
const PERSONA_ID_PATTERN = /^[a-z0-9][a-z0-9-]{1,63}$/;
const MAX_FILE_CHARS = 8_000;
const MAX_TOTAL_CHARS = 16_000;
const MAX_INTRO_CHARS = 160;
const PERSONA_FILENAME_SET = new Set<string>(AVATAR_PERSONA_FILENAMES);

export async function readAvatarPersonaProfile(
  avatarId: string,
  root = process.cwd(),
): Promise<AvatarPersonaProfile | null> {
  if (!AVATAR_ID_PATTERN.test(avatarId)) throw new Error("Avatar ID 无效");
  const linksPath = path.join(root, "config", "avatar-persona-links.json");
  let rawLinks: string;
  try {
    rawLinks = await readFile(linksPath, "utf8");
  } catch (error) {
    if (isMissingFile(error)) return null;
    throw error;
  }
  const payload = JSON.parse(rawLinks) as { version?: unknown; links?: unknown };
  if (payload.version !== 2 || !isLinkRecord(payload.links)) {
    throw new Error("Avatar Persona 关联目录无效");
  }
  const link = payload.links[avatarId];
  if (!link) return null;
  const { personaId, avatarDisplayName } = link;
  if (!PERSONA_ID_PATTERN.test(personaId)) throw new Error("Persona ID 无效");
  if (!validDisplayName(avatarDisplayName)) throw new Error("Avatar 显示名称无效");

  const personaRoot = path.join(root, "config", "personas", personaId);
  const files: AvatarPersonaFile[] = [];
  let totalChars = 0;
  for (const filename of AVATAR_PERSONA_FILENAMES) {
    let content: string;
    try {
      content = (await readFile(path.join(personaRoot, filename), "utf8")).trim();
    } catch (error) {
      if (isMissingFile(error)) continue;
      throw error;
    }
    if (content.length > MAX_FILE_CHARS) throw new Error(`Persona 文件过大：${filename}`);
    totalChars += content.length;
    if (totalChars > MAX_TOTAL_CHARS) throw new Error("Persona 配置总长度过大");
    if (content) files.push({ filename, content });
  }
  if (files.length === 0) return null;
  const present = new Set(files.map((file) => file.filename));
  const missingRequired = REQUIRED_AVATAR_PERSONA_FILENAMES.filter((filename) => !present.has(filename));
  if (missingRequired.length > 0) {
    throw new Error(`Persona 缺少必需文件：${missingRequired.join("、")}`);
  }
  const linkedAvatarIds = Object.entries(payload.links)
    .filter(([, otherLink]) => otherLink.personaId === personaId)
    .map(([otherAvatarId]) => otherAvatarId)
    .sort();
  return {
    avatarId,
    personaId,
    personaName: identityHeading(files) ?? personaId,
    avatarDisplayName: avatarDisplayName.trim(),
    files,
    linkedAvatarIds,
  };
}

export async function listPersonas(root = process.cwd()): Promise<PersonaSummary[]> {
  const personasRoot = path.join(root, "config", "personas");
  let entries: string[];
  try {
    entries = (await readdir(personasRoot, { withFileTypes: true }))
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name)
      .filter((name) => PERSONA_ID_PATTERN.test(name));
  } catch (error) {
    if (isMissingFile(error)) return [];
    throw error;
  }
  const links = await readLinksRecord(root);
  const personas = await Promise.all(entries.map(async (personaId) => {
    let identityContent = "";
    try {
      identityContent = (await readFile(path.join(personasRoot, personaId, "IDENTITY.md"), "utf8")).trim();
    } catch (error) {
      if (!isMissingFile(error)) throw error;
    }
    const personaName = identityHeading([{ filename: "IDENTITY.md", content: identityContent }]) ?? personaId;
    const linkedAvatarIds = linkedAvatarIdsForPersona(links, personaId);
    const intro = await readPersonaIntro(path.join(personasRoot, personaId), identityContent);
    return { personaId, personaName, ...(intro ? { intro } : {}), linkedAvatarIds };
  }));
  return personas.sort((a, b) => a.personaId.localeCompare(b.personaId));
}

export async function readPersonaProfile(
  personaId: string,
  root = process.cwd(),
): Promise<PersonaProfile | null> {
  if (!PERSONA_ID_PATTERN.test(personaId)) throw new Error("Persona ID 无效");
  const personaRoot = path.join(root, "config", "personas", personaId);
  const files: AvatarPersonaFile[] = [];
  let totalChars = 0;
  for (const filename of AVATAR_PERSONA_FILENAMES) {
    let content: string;
    try {
      content = (await readFile(path.join(personaRoot, filename), "utf8")).trim();
    } catch (error) {
      if (isMissingFile(error)) continue;
      throw error;
    }
    if (content.length > MAX_FILE_CHARS) throw new Error(`Persona 文件过大：${filename}`);
    totalChars += content.length;
    if (totalChars > MAX_TOTAL_CHARS) throw new Error("Persona 配置总长度过大");
    if (content) files.push({ filename, content });
  }
  if (files.length === 0) return null;
  const links = await readLinksRecord(root);
  const intro = await readPersonaIntro(personaRoot, files.find((file) => file.filename === "IDENTITY.md")?.content ?? "");
  return {
    personaId,
    personaName: identityHeading(files) ?? personaId,
    ...(intro ? { intro } : {}),
    files,
    linkedAvatarIds: linkedAvatarIdsForPersona(links, personaId),
  };
}

export function normalizePersonaIntro(value: unknown): string {
  if (typeof value !== "string") throw new Error("Persona 简介格式无效");
  const intro = value.trim().replace(/\s+/g, " ");
  if (intro.length > MAX_INTRO_CHARS) throw new Error("Persona 简介超过 160 字");
  return intro;
}

export async function writePersonaIntro(personaId: string, intro: string, root = process.cwd()): Promise<void> {
  if (!PERSONA_ID_PATTERN.test(personaId)) throw new Error("Persona ID 无效");
  const normalized = normalizePersonaIntro(intro);
  const personaRoot = path.join(root, "config", "personas", personaId);
  try {
    await readFile(path.join(personaRoot, "IDENTITY.md"), "utf8");
  } catch (error) {
    if (isMissingFile(error)) throw new Error("找不到 Persona");
    throw error;
  }
  await atomicWriteFile(path.join(personaRoot, "INTRO.txt"), normalized);
}

export async function renamePersona(personaId: string, displayName: string, root = process.cwd()): Promise<PersonaProfile> {
  if (!PERSONA_ID_PATTERN.test(personaId)) throw new Error("Persona ID 无效");
  if (!validDisplayName(displayName)) throw new Error("人设名称无效");
  const profile = await readPersonaProfile(personaId, root);
  if (!profile) throw new Error("找不到 Persona");
  const identity = profile.files.find((file) => file.filename === "IDENTITY.md");
  if (!identity) throw new Error("Persona 缺少必需文件：IDENTITY.md");
  const content = identity.content.replace(/^#\s+[^\r\n]*(?:\r?\n)?/, "").trimStart();
  const next = content ? `# ${displayName.trim()}\n\n${content}` : `# ${displayName.trim()}`;
  await writeAvatarPersonaFiles(personaId, [{ filename: "IDENTITY.md", content: next }], root);
  return (await readPersonaProfile(personaId, root)) as PersonaProfile;
}

export async function archivePersona(personaId: string, root = process.cwd()): Promise<void> {
  if (!PERSONA_ID_PATTERN.test(personaId)) throw new Error("Persona ID 无效");
  if (isBuiltinPersonaId(personaId)) throw new Error("内置人设不能删除");
  const profile = await readPersonaProfile(personaId, root);
  if (!profile) throw new Error("找不到 Persona");
  if (profile.linkedAvatarIds.length || await personaIsUsedByRole(personaId, root)) {
    throw new Error("人设仍被数字人或角色使用，不能删除");
  }
  const archiveRoot = path.join(root, ".openrealtime", "persona-trash");
  await mkdir(archiveRoot, { recursive: true, mode: 0o700 });
  await rename(path.join(root, "config", "personas", personaId), path.join(archiveRoot, `${personaId}-${Date.now()}-${randomUUID()}`));
}

async function personaIsUsedByRole(personaId: string, root: string): Promise<boolean> {
  const sharedCatalogRoot = root === process.cwd() && process.env.ROLE_CATALOG_DIR?.trim()
    ? path.resolve(process.env.ROLE_CATALOG_DIR.trim()) : path.join(root, ".openrealtime", "role-catalog");
  if (await roleCatalogUsesPersona(path.join(sharedCatalogRoot, "roles.json"), personaId)) return true;
  const personalRoot = root === process.cwd() && process.env.OPENREALTIME_PERSONAL_MOTION_PATH?.trim()
    ? path.resolve(process.env.OPENREALTIME_PERSONAL_MOTION_PATH.trim()) : path.join(root, ".openrealtime", "personal-motion");
  let owners;
  try { owners = await readdir(personalRoot, { withFileTypes: true }); }
  catch (error) { if (isMissingFile(error)) return false; throw error; }
  for (const owner of owners) {
    if (owner.isDirectory() && await roleCatalogUsesPersona(path.join(personalRoot, owner.name, "roles", "catalog.json"), personaId)) return true;
  }
  return false;
}

async function roleCatalogUsesPersona(catalogPath: string, personaId: string): Promise<boolean> {
  let raw;
  try { raw = await readFile(catalogPath, "utf8"); }
  catch (error) { if (isMissingFile(error)) return false; throw error; }
  const records = JSON.parse(raw) as unknown;
  if (!Array.isArray(records)) throw new Error("角色目录结构异常");
  return records.some((record) => record && typeof record === "object" && !record.deleted_at && record.persona_id === personaId);
}

async function readPersonaIntro(personaRoot: string, identityContent: string): Promise<string> {
  try {
    return normalizePersonaIntro(await readFile(path.join(personaRoot, "INTRO.txt"), "utf8"));
  } catch (error) {
    if (!isMissingFile(error)) throw error;
  }
  const positioning = identityContent.match(/^\s*[-*]\s*(?:Persona\s*)?(?:定位|简介|风格)\s*[：:]\s*(.+)$/mi)?.[1];
  return normalizePersonaIntro((positioning || "").slice(0, MAX_INTRO_CHARS));
}

export async function createPersona(
  personaId: string,
  files: AvatarPersonaFile[],
  root = process.cwd(),
): Promise<void> {
  if (!PERSONA_ID_PATTERN.test(personaId)) throw new Error("Persona ID 无效");
  const personaRoot = path.join(root, "config", "personas", personaId);
  let alreadyExists = true;
  try {
    await readdir(personaRoot);
  } catch (error) {
    if (!isMissingFile(error)) throw error;
    alreadyExists = false;
  }
  if (alreadyExists) throw new Error("Persona 已存在");

  const present = new Set(files.map((file) => file.filename));
  const missingRequired = REQUIRED_AVATAR_PERSONA_FILENAMES.filter((filename) => !present.has(filename));
  if (missingRequired.length > 0) {
    throw new Error(`Persona 缺少必需文件：${missingRequired.join("、")}`);
  }
  await writeAvatarPersonaFiles(personaId, files, root);
}

export async function writeAvatarPersonaFiles(
  personaId: string,
  files: AvatarPersonaFile[],
  root = process.cwd(),
): Promise<void> {
  if (!PERSONA_ID_PATTERN.test(personaId)) throw new Error("Persona ID 无效");
  if (files.length === 0) throw new Error("没有需要保存的 Persona 文件");
  let totalChars = 0;
  for (const file of files) {
    if (!PERSONA_FILENAME_SET.has(file.filename)) throw new Error(`Persona 文件名无效：${file.filename}`);
    if (file.content.length > MAX_FILE_CHARS) throw new Error(`Persona 文件过大：${file.filename}`);
    totalChars += file.content.length;
  }
  if (totalChars > MAX_TOTAL_CHARS) throw new Error("Persona 配置总长度过大");

  const personaRoot = path.join(root, "config", "personas", personaId);
  await mkdir(personaRoot, { recursive: true });
  for (const file of files) {
    await atomicWriteFile(path.join(personaRoot, file.filename), file.content);
  }
}

export async function switchAvatarPersona(
  avatarId: string,
  personaId: string,
  avatarDisplayName?: string,
  root = process.cwd(),
): Promise<void> {
  if (!AVATAR_ID_PATTERN.test(avatarId)) throw new Error("Avatar ID 无效");
  if (!PERSONA_ID_PATTERN.test(personaId)) throw new Error("Persona ID 无效");

  const personaRoot = path.join(root, "config", "personas", personaId);
  const present = new Set<string>();
  for (const filename of AVATAR_PERSONA_FILENAMES) {
    try {
      await readFile(path.join(personaRoot, filename), "utf8");
      present.add(filename);
    } catch (error) {
      if (!isMissingFile(error)) throw error;
    }
  }
  const missingRequired = REQUIRED_AVATAR_PERSONA_FILENAMES.filter((filename) => !present.has(filename));
  if (missingRequired.length > 0) throw new Error(`目标 Persona 缺少必需文件：${missingRequired.join("、")}`);

  const linksPath = path.join(root, "config", "avatar-persona-links.json");
  const rawLinks = await readFile(linksPath, "utf8");
  const payload = JSON.parse(rawLinks) as { version?: unknown; links?: unknown };
  if (payload.version !== 2 || !isLinkRecord(payload.links)) {
    throw new Error("Avatar Persona 关联目录无效");
  }
  const existingLink = payload.links[avatarId];
  let nextLink: AvatarPersonaLink;
  if (existingLink) {
    nextLink = { ...existingLink, personaId };
  } else {
    if (!avatarDisplayName || !validDisplayName(avatarDisplayName)) {
      throw new Error("缺少 Avatar 显示名称");
    }
    nextLink = { personaId, avatarDisplayName: avatarDisplayName.trim() };
  }

  const nextLinks = { ...payload.links, [avatarId]: nextLink };
  await atomicWriteFile(linksPath, JSON.stringify({ version: 2, links: nextLinks }, null, 2));
}

async function readLinksRecord(root: string): Promise<Record<string, AvatarPersonaLink>> {
  const linksPath = path.join(root, "config", "avatar-persona-links.json");
  let rawLinks: string;
  try {
    rawLinks = await readFile(linksPath, "utf8");
  } catch (error) {
    if (isMissingFile(error)) return {};
    throw error;
  }
  const payload = JSON.parse(rawLinks) as { version?: unknown; links?: unknown };
  if (payload.version !== 2 || !isLinkRecord(payload.links)) {
    throw new Error("Avatar Persona 关联目录无效");
  }
  return payload.links;
}

function linkedAvatarIdsForPersona(links: Record<string, AvatarPersonaLink>, personaId: string): string[] {
  return Object.entries(links)
    .filter(([, link]) => link.personaId === personaId)
    .map(([avatarId]) => avatarId)
    .sort();
}

async function atomicWriteFile(destination: string, content: string) {
  const temporary = path.join(path.dirname(destination), `.${path.basename(destination)}.${randomUUID()}.tmp`);
  await writeFile(temporary, content, { flag: "wx", mode: 0o600 });
  await rename(temporary, destination);
}

function identityHeading(files: AvatarPersonaFile[]) {
  const identity = files.find((file) => file.filename === "IDENTITY.md")?.content;
  return identity?.match(/^#\s+(.+)$/m)?.[1]?.trim() || null;
}

type AvatarPersonaLink = { personaId: string; avatarDisplayName: string };

function isLinkRecord(value: unknown): value is Record<string, AvatarPersonaLink> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    && Object.values(value).every((item) => (
      item !== null
      && typeof item === "object"
      && !Array.isArray(item)
      && typeof (item as AvatarPersonaLink).personaId === "string"
      && typeof (item as AvatarPersonaLink).avatarDisplayName === "string"
    ));
}

function validDisplayName(value: string) {
  const trimmed = value.trim();
  return Boolean(trimmed) && trimmed.length <= 80 && !/[\r\n]/.test(value);
}

function isMissingFile(error: unknown) {
  return Boolean(error && typeof error === "object" && "code" in error && error.code === "ENOENT");
}

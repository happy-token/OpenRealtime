import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { personalLibraryOwnerDir } from "./personal-motion-library";
import type { WebUser } from "./user-session";

const ROLE_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{1,159}$/;

function preferencePath(user: WebUser) {
  return path.join(personalLibraryOwnerDir(user), "default-role.json");
}

export async function readUserDefaultRole(user: WebUser): Promise<string | null> {
  try {
    const value: unknown = JSON.parse(await readFile(preferencePath(user), "utf8"));
    if (!value || typeof value !== "object" || !("roleId" in value)) return null;
    const roleId = value.roleId;
    return typeof roleId === "string" && ROLE_ID.test(roleId) ? roleId : null;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
}

export async function writeUserDefaultRole(user: WebUser, roleId: string): Promise<void> {
  if (!ROLE_ID.test(roleId)) throw new Error("角色 ID 无效");
  const target = preferencePath(user);
  await mkdir(path.dirname(target), { recursive: true, mode: 0o700 });
  const temporary = `${target}.${randomUUID()}.tmp`;
  await writeFile(temporary, JSON.stringify({ roleId }), { flag: "wx", mode: 0o600 });
  await rename(temporary, target);
}

import { cookies } from "next/headers";
import {
  ADMIN_SESSION_COOKIE,
  adminAuthConfigFromEnv,
  adminLoginDefaultsFromEnv,
  verifyAdminSessionToken,
} from "./admin-auth";

export async function currentAdmin(): Promise<{ username: string } | null> {
  const config = adminAuthConfigFromEnv();
  if (!config) return null;
  const cookieStore = await cookies();
  return verifyAdminSessionToken(cookieStore.get(ADMIN_SESSION_COOKIE)?.value, config);
}

export function isAdminConfigured(): boolean {
  return adminAuthConfigFromEnv() !== null;
}

export function adminLoginDefaults() {
  return adminLoginDefaultsFromEnv();
}

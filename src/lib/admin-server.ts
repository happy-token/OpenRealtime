import { cookies } from "next/headers";
import {
  ADMIN_SESSION_COOKIE,
  adminAuthConfigFromEnv,
  adminLoginDefaultsFromEnv,
  verifyAdminSessionToken,
} from "./admin-auth";
import { isAppAdmin } from "./app-admin-accounts";
import { userFromRequest, type WebUser } from "./user-session";

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

/** The signed-in application account, only when it is a granted app admin. */
export async function currentAppAdmin(request: Request): Promise<WebUser | null> {
  const user = await userFromRequest(request);
  if (!user) return null;
  return await isAppAdmin(user) ? user : null;
}

/** Account management uses the same signed-in application identity as diagnostics. */
export async function isAuthorizedForAdminAccountManagement(request: Request): Promise<boolean> {
  return Boolean(await currentAppAdmin(request));
}

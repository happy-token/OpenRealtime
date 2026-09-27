import { ADMIN_SESSION_COOKIE, adminAuthConfigFromEnv, verifyAdminSessionToken } from "./admin-auth";
import { userFromRequest, type WebUser } from "./user-session";

export type ProviderActor = { user: WebUser; admin: boolean; signedIn: boolean };

export async function providerActor(request: Request): Promise<ProviderActor | null> {
  const user = await userFromRequest(request);
  const cookie = request.headers.get("cookie")?.split(";").map((part) => part.trim())
    .find((part) => part.startsWith(`${ADMIN_SESSION_COOKIE}=`))?.slice(ADMIN_SESSION_COOKIE.length + 1);
  const config = adminAuthConfigFromEnv();
  const admin = Boolean(config && verifyAdminSessionToken(cookie, config));
  if (!user && !admin) return null;
  return { user: user ?? { issuer: "platform", subject: "admin" }, admin, signedIn: Boolean(user) };
}

export function validInstanceId(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
}

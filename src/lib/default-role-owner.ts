import { authorizeAvatarAssetRequest } from "./avatar-assets-server";
import { userFromRequest, type WebUser } from "./user-session";

export const LOCAL_DEFAULT_ROLE_OWNER: WebUser = { issuer: "openrealtime-local", subject: "avatar-admin" };

export async function defaultRoleOwner(request: Request, mutation = false): Promise<WebUser | null> {
  const user = await userFromRequest(request);
  if (user) return user;
  return authorizeAvatarAssetRequest(request, mutation) ? LOCAL_DEFAULT_ROLE_OWNER : null;
}

export function localDefaultRoleOwnerForPage(host: string | null, env: NodeJS.ProcessEnv = process.env): WebUser | null {
  if (env.NODE_ENV !== "development"
    || env.AVATAR_LOCAL_TEST_MODE !== "true"
    || env.AVATAR_EVALUATION_LOOPBACK_BOUND !== "true"
    || !host) return null;
  try {
    const hostname = new URL(`http://${host}`).hostname;
    return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "[::1]"
      ? LOCAL_DEFAULT_ROLE_OWNER : null;
  } catch { return null; }
}

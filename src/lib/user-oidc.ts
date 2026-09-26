import { createCipheriv, createDecipheriv, createHash, randomBytes } from "node:crypto";
import * as oidc from "openid-client";

export const OIDC_FLOW_COOKIE = "openrealtime_oidc_flow";
const FLOW_SECONDS = 10 * 60;

interface OidcConfig {
  issuer: URL;
  clientId: string;
  clientSecret: string;
  publicOrigin: URL;
  flowSecret: string;
}

interface LoginFlow {
  state: string;
  nonce: string;
  verifier: string;
  returnTo: string;
  expiresAt: number;
}

let cachedDiscovery: { key: string; value: Promise<oidc.Configuration> } | undefined;

function configFromEnv(): OidcConfig {
  const issuerValue = process.env.VOICEAGENT_CASDOOR_ISSUER;
  const clientId = process.env.VOICEAGENT_CASDOOR_CLIENT_ID;
  const clientSecret = process.env.VOICEAGENT_CASDOOR_CLIENT_SECRET;
  const originValue = process.env.VOICEAGENT_PUBLIC_ORIGIN;
  const flowSecret = process.env.VOICEAGENT_USER_SESSION_SECRET;
  if (!issuerValue || !clientId || !clientSecret || !originValue || !flowSecret || flowSecret.length < 32) {
    throw new Error("用户登录尚未配置");
  }
  const issuer = new URL(issuerValue);
  const publicOrigin = new URL(originValue);
  if (publicOrigin.pathname !== "/" || publicOrigin.search || publicOrigin.hash
    || !secureEndpoint(issuer) || !secureEndpoint(publicOrigin)) {
    throw new Error("用户登录地址配置无效");
  }
  return { issuer, clientId, clientSecret, publicOrigin, flowSecret };
}

function secureEndpoint(url: URL): boolean {
  return url.protocol === "https:"
    || (process.env.NODE_ENV !== "production" && url.protocol === "http:"
      && (url.hostname === "127.0.0.1" || url.hostname === "localhost"));
}

function flowKey(config: OidcConfig): Buffer {
  return createHash("sha256").update(config.flowSecret).digest();
}

function sealFlow(flow: LoginFlow, config: OidcConfig): string {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", flowKey(config), iv);
  const encrypted = Buffer.concat([cipher.update(JSON.stringify(flow), "utf8"), cipher.final()]);
  return Buffer.concat([iv, cipher.getAuthTag(), encrypted]).toString("base64url");
}

function openFlow(value: string, config: OidcConfig): LoginFlow | null {
  try {
    const bytes = Buffer.from(value, "base64url");
    if (bytes.length < 29) return null;
    const decipher = createDecipheriv("aes-256-gcm", flowKey(config), bytes.subarray(0, 12));
    decipher.setAuthTag(bytes.subarray(12, 28));
    const decoded: unknown = JSON.parse(Buffer.concat([
      decipher.update(bytes.subarray(28)), decipher.final(),
    ]).toString("utf8"));
    if (!decoded || typeof decoded !== "object") return null;
    const flow = decoded as Partial<LoginFlow>;
    return typeof flow.state === "string" && typeof flow.nonce === "string"
      && typeof flow.verifier === "string" && typeof flow.returnTo === "string"
      && typeof flow.expiresAt === "number" && Date.now() < flow.expiresAt
      ? flow as LoginFlow : null;
  } catch {
    return null;
  }
}

async function discovery(config: OidcConfig): Promise<oidc.Configuration> {
  const key = `${config.issuer.href}\0${config.clientId}\0${config.clientSecret}`;
  if (!cachedDiscovery || cachedDiscovery.key !== key) {
    cachedDiscovery = {
      key,
      value: oidc.discovery(config.issuer, config.clientId, config.clientSecret),
    };
  }
  try {
    return await cachedDiscovery.value;
  } catch (error) {
    cachedDiscovery = undefined;
    throw error;
  }
}

export function safeReturnPath(value: string | null): string {
  return value && value.startsWith("/") && !value.startsWith("//") && !value.includes("\\")
    ? value : "/settings/providers";
}

export async function beginOidcLogin(returnTo: string): Promise<{ redirectUrl: URL; flowCookie: string }> {
  const config = configFromEnv();
  const client = await discovery(config);
  const verifier = oidc.randomPKCECodeVerifier();
  const flow: LoginFlow = {
    verifier,
    state: oidc.randomState(),
    nonce: oidc.randomNonce(),
    returnTo: safeReturnPath(returnTo),
    expiresAt: Date.now() + FLOW_SECONDS * 1000,
  };
  const redirectUrl = oidc.buildAuthorizationUrl(client, {
    redirect_uri: new URL("/api/user/callback", config.publicOrigin).href,
    scope: "openid profile email",
    response_type: "code",
    code_challenge: await oidc.calculatePKCECodeChallenge(verifier),
    code_challenge_method: "S256",
    state: flow.state,
    nonce: flow.nonce,
  });
  return { redirectUrl, flowCookie: sealFlow(flow, config) };
}

export async function finishOidcLogin(
  callbackUrl: URL,
  flowCookie: string | undefined,
): Promise<{ issuer: string; subject: string; returnTo: string }> {
  const config = configFromEnv();
  const flow = flowCookie && openFlow(flowCookie, config);
  if (!flow) throw new Error("登录状态已过期，请重新登录");
  if (callbackUrl.origin !== config.publicOrigin.origin
    || callbackUrl.pathname !== "/api/user/callback") {
    throw new Error("登录回调地址无效");
  }
  const client = await discovery(config);
  const tokens = await oidc.authorizationCodeGrant(client, callbackUrl, {
    pkceCodeVerifier: flow.verifier,
    expectedNonce: flow.nonce,
    expectedState: flow.state,
    idTokenExpected: true,
  });
  const claims = tokens.claims();
  if (!claims?.sub) throw new Error("登录身份无效");
  return { issuer: claims.iss, subject: claims.sub, returnTo: flow.returnTo };
}

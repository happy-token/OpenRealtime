import { adminAuthConfigFromEnv } from "./admin-auth";
import { avatarEvaluationPreviewPolicyFromEnv, isSameOriginAvatarPreviewRequest } from "./avatar-evaluation-preview";
import { resolveAvatarRendererRuntime } from "./avatar-renderer-runtime";

export type AvatarCapabilityId = "assets" | "anam" | "heygen" | "localRenderer";
export interface AvatarCapability {
  state: "available" | "login_required" | "not_configured";
  message: string;
}
export type AvatarCapabilities = Record<AvatarCapabilityId, AvatarCapability>;

/** Configuration/admission preflight, not a provider health check. Never exposes secrets. */
export function avatarCapabilities(
  request: Request,
  assetAccess: boolean,
  admin: boolean,
  env: NodeJS.ProcessEnv = process.env,
): AvatarCapabilities {
  const access: AvatarCapability = adminAuthConfigFromEnv(env)
    ? { state: "login_required", message: "请先登录管理员账号，再使用此能力。" }
    : { state: "not_configured", message: "此环境尚未开放数字人管理，请联系管理员完成访问配置。" };
  const configured = (ready: boolean, message: string): AvatarCapability => ready
    ? { state: "available", message: "配置已就绪，启动时会检查服务连接。" }
    : { state: "not_configured", message };
  const policy = avatarEvaluationPreviewPolicyFromEnv(env);
  let rendererReady = false;
  try { rendererReady = resolveAvatarRendererRuntime(env) !== null; } catch { /* Invalid config stays unavailable. */ }
  return {
    assets: assetAccess ? { state: "available", message: "可以管理数字人资产。" } : access,
    anam: assetAccess ? { state: "available", message: "启动时可填写 Anam API Key。" } : access,
    heygen: assetAccess ? configured(Boolean(env.LIVEAVATAR_API_KEY?.trim() && env.LIVEAVATAR_AVATAR_ID?.trim()), "HeyGen 尚未配置凭据或形象，请联系管理员。") : access,
    localRenderer: !policy.enabled
      ? { state: "not_configured", message: "此环境尚未启用本地数字人预览。" }
      : !(admin || (policy.localDevelopmentAccess && isSameOriginAvatarPreviewRequest(request)))
        ? access
        : configured(rendererReady, "本地口型服务未启用或配置无效，请联系管理员。"),
  };
}

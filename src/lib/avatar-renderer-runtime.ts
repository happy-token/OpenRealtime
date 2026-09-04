export type AvatarRendererMode = "managed" | "external";

export interface AvatarRendererRuntime {
  mode: AvatarRendererMode;
  internalUrl: string;
  publicUrl: string;
  rendererId: "livetalking-wav2lip256" | "livetalking-wav2lip96";
  modelId: "wav2lip256" | "wav2lip96";
  modelSize: 256 | 96;
  port: number;
}

type AvatarRendererEnvironment = Record<string, string | undefined> & {
  OPENREALTIME_AVATAR_RENDERER_MODE?: string;
  OPENREALTIME_AVATAR_RENDERER_URL?: string;
  OPENREALTIME_AVATAR_RENDERER_PUBLIC_URL?: string;
  OPENREALTIME_AVATAR_RENDERER_WAV2LIP96_URL?: string;
  OPENREALTIME_AVATAR_RENDERER_WAV2LIP96_PUBLIC_URL?: string;
};

const DEFAULT_RENDERER_URL = "http://127.0.0.1:8010";

export function resolveAvatarRendererRuntime(
  env: AvatarRendererEnvironment = process.env,
): AvatarRendererRuntime | null {
  return resolveAvatarRendererRuntimeForModel("wav2lip256", env);
}

export function resolveAvatarRendererRuntimeForModel(
  modelId: "wav2lip256" | "wav2lip96",
  env: AvatarRendererEnvironment = process.env,
): AvatarRendererRuntime | null {
  const mode = env.OPENREALTIME_AVATAR_RENDERER_MODE?.trim() || "managed";
  if (mode === "disabled") return null;
  if (mode !== "managed" && mode !== "external") {
    throw new Error("OPENREALTIME_AVATAR_RENDERER_MODE must be managed, external, or disabled");
  }

  const isCompatibilityModel = modelId === "wav2lip96";
  if (isCompatibilityModel && mode === "external"
    && !env.OPENREALTIME_AVATAR_RENDERER_WAV2LIP96_URL?.trim()) {
    throw new Error("External Wav2Lip 96 renderer URL is not configured");
  }
  const internalUrl = normalizeRendererUrl(isCompatibilityModel
    ? env.OPENREALTIME_AVATAR_RENDERER_WAV2LIP96_URL?.trim() || "http://127.0.0.1:8011"
    : env.OPENREALTIME_AVATAR_RENDERER_URL?.trim() || DEFAULT_RENDERER_URL);
  const publicUrl = normalizeRendererUrl(isCompatibilityModel
    ? env.OPENREALTIME_AVATAR_RENDERER_WAV2LIP96_PUBLIC_URL?.trim() || internalUrl
    : env.OPENREALTIME_AVATAR_RENDERER_PUBLIC_URL?.trim() || internalUrl);
  const modelSize = modelId === "wav2lip256" ? 256 : 96;
  return {
    mode,
    internalUrl,
    publicUrl,
    rendererId: `livetalking-${modelId}`,
    modelId,
    modelSize,
    port: portFromUrl(internalUrl),
  };
}

function portFromUrl(value: string): number {
  const url = new URL(value);
  return Number(url.port || (url.protocol === "https:" ? 443 : 80));
}

function normalizeRendererUrl(value: string): string {
  const url = new URL(value);
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error("Avatar renderer URL must use http or https");
  }
  if (url.username || url.password || url.search || url.hash) {
    throw new Error("Avatar renderer URL cannot contain credentials, query, or fragment");
  }
  url.pathname = url.pathname.replace(/\/+$/, "") || "/";
  return url.toString().replace(/\/$/, "");
}

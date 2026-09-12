import {
  AVATAR_IDENTITY_CHOICES,
  LIP_SYNC_CHOICES,
  MAC_LIP_SYNC_RUNTIME_CHOICES,
  VIDEO_BASE_CHOICES,
} from "./segmented-avatar-config";
import {
  PRESENTATION_MODE_OPTIONS,
  parsePresentationMode,
  type PresentationMode,
} from "@/components/call/presentation-model";

export type ExperienceMode = PresentationMode;

export const EXPERIENCE_MODE_OPTIONS = PRESENTATION_MODE_OPTIONS;

export function parseExperienceMode(value: unknown): ExperienceMode {
  return parsePresentationMode(value);
}

export type AvatarRenderPath = "hosted" | "segmented" | "orchestrated";
export type AvatarProvider = "anam" | "heygen" | "custom";
export type AvatarSurface = "fullbleed" | "stage" | "pip";
export type AvatarFraming = "close" | "half" | "full";
export type AvatarRatio = "16:9" | "9:16" | "1:1";
export type AvatarQuality = "quality" | "balanced" | "latency";

const SEGMENTED_AVATAR_IDS = new Set(AVATAR_IDENTITY_CHOICES.map((choice) => choice.id));
const SEGMENTED_VIDEO_IDS = new Set(VIDEO_BASE_CHOICES.map((choice) => choice.id));
const SEGMENTED_LIP_SYNC_IDS = new Set([
  ...LIP_SYNC_CHOICES.map((choice) => choice.id),
  ...MAC_LIP_SYNC_RUNTIME_CHOICES.map((choice) => choice.id),
]);

export interface AvatarDisplayConfig {
  renderPath: AvatarRenderPath;
  motionTalkingVariantId?: string;
  provider: AvatarProvider;
  avatarProfileId: string;
  hostedAvatarDisplayName?: string;
  hostedAvatarImageUrl?: string;
  segmentedPresetId: string;
  segmentedAvatarId: string;
  segmentedDisplayName?: string;
  segmentedVideoId: string;
  segmentedAvatarActionId: string;
  segmentedLipSyncId: string;
  surface: AvatarSurface;
  framing: AvatarFraming;
  ratio: AvatarRatio;
  quality: AvatarQuality;
  fallbackToClassic: true;
}

export const DEFAULT_AVATAR_DISPLAY_CONFIG: AvatarDisplayConfig = {
  renderPath: "hosted",
  provider: "anam",
  avatarProfileId: "default-anam",
  segmentedPresetId: "shuchang",
  segmentedAvatarId: "shuchang",
  segmentedDisplayName: "Shuchang",
  segmentedVideoId: "liveportrait-optimized",
  segmentedAvatarActionId: "builtin:shuchang-realtime-idle",
  segmentedLipSyncId: "wav2lip256",
  surface: "fullbleed",
  framing: "full",
  ratio: "16:9",
  quality: "quality",
  fallbackToClassic: true,
};

export function parseAvatarDisplayConfig(value: unknown): AvatarDisplayConfig {
  if (!value || typeof value !== "object") return DEFAULT_AVATAR_DISPLAY_CONFIG;
  const draft = value as Record<string, unknown>;
  const avatarProfileId = typeof draft.avatarProfileId === "string" && draft.avatarProfileId.trim()
    ? draft.avatarProfileId.trim()
    : DEFAULT_AVATAR_DISPLAY_CONFIG.avatarProfileId;
  const hostedAvatarDisplayName = typeof draft.hostedAvatarDisplayName === "string" && draft.hostedAvatarDisplayName.trim()
    ? draft.hostedAvatarDisplayName.trim().slice(0, 50)
    : undefined;
  const hostedAvatarImageUrl = parseHostedAvatarImageUrl(draft.hostedAvatarImageUrl);
  const parsed: AvatarDisplayConfig = {
    renderPath: draft.renderPath === "orchestrated" ? "orchestrated" : draft.renderPath === "segmented" ? "segmented" : "hosted",
    motionTalkingVariantId: typeof draft.motionTalkingVariantId === "string" ? draft.motionTalkingVariantId.slice(0, 128) : undefined,
    provider: draft.provider === "heygen" || draft.provider === "custom" ? draft.provider : "anam",
    avatarProfileId,
    hostedAvatarDisplayName,
    hostedAvatarImageUrl,
    segmentedPresetId: typeof draft.segmentedPresetId === "string" && SEGMENTED_AVATAR_IDS.has(draft.segmentedPresetId)
      ? draft.segmentedPresetId
      : DEFAULT_AVATAR_DISPLAY_CONFIG.segmentedPresetId,
    segmentedAvatarId: typeof draft.segmentedAvatarId === "string"
      && /^[a-zA-Z0-9][a-zA-Z0-9._:-]{1,127}$/.test(draft.segmentedAvatarId)
      ? draft.segmentedAvatarId
      : typeof draft.segmentedPresetId === "string" && SEGMENTED_AVATAR_IDS.has(draft.segmentedPresetId) && draft.segmentedPresetId !== "custom-upload"
        ? draft.segmentedPresetId
        : DEFAULT_AVATAR_DISPLAY_CONFIG.segmentedAvatarId,
    segmentedDisplayName: typeof draft.segmentedDisplayName === "string" && draft.segmentedDisplayName.trim()
      ? draft.segmentedDisplayName.trim().slice(0, 50)
      : DEFAULT_AVATAR_DISPLAY_CONFIG.segmentedDisplayName,
    segmentedVideoId: typeof draft.segmentedVideoId === "string" && SEGMENTED_VIDEO_IDS.has(draft.segmentedVideoId)
      ? draft.segmentedVideoId
      : DEFAULT_AVATAR_DISPLAY_CONFIG.segmentedVideoId,
    segmentedAvatarActionId: typeof draft.segmentedAvatarActionId === "string"
      && (!draft.segmentedAvatarActionId || /^[a-zA-Z0-9][a-zA-Z0-9._:-]{1,127}$/.test(draft.segmentedAvatarActionId))
      ? draft.segmentedAvatarActionId
      : DEFAULT_AVATAR_DISPLAY_CONFIG.segmentedAvatarActionId,
    segmentedLipSyncId: typeof draft.segmentedLipSyncId === "string" && SEGMENTED_LIP_SYNC_IDS.has(draft.segmentedLipSyncId)
      ? draft.segmentedLipSyncId
      : DEFAULT_AVATAR_DISPLAY_CONFIG.segmentedLipSyncId,
    surface: draft.surface === "stage" || draft.surface === "pip" ? draft.surface : "fullbleed",
    framing: draft.framing === "close" || draft.framing === "half" ? draft.framing : "full",
    ratio: draft.ratio === "9:16" || draft.ratio === "1:1" ? draft.ratio : "16:9",
    quality: draft.quality === "balanced" || draft.quality === "latency" ? draft.quality : "quality",
    fallbackToClassic: true,
  };
  if (parsed.segmentedPresetId === "liteavatar-preset") {
    return { ...parsed, segmentedVideoId: "avatar-bundled", segmentedLipSyncId: "liteavatar" };
  }
  if (parsed.segmentedPresetId === "dh-live-preset") {
    return { ...parsed, segmentedVideoId: "avatar-bundled", segmentedLipSyncId: "dh-live-mini-v1" };
  }
  if (
    parsed.renderPath === "segmented"
    && parsed.segmentedAvatarId === "shuchang"
    && parsed.segmentedVideoId === "liveportrait-optimized"
    && parsed.segmentedLipSyncId === "dh-live-mini-v1"
  ) {
    return { ...parsed, segmentedLipSyncId: "wav2lip256" };
  }
  if (parsed.segmentedVideoId === "avatar-bundled") {
    return { ...parsed, segmentedVideoId: DEFAULT_AVATAR_DISPLAY_CONFIG.segmentedVideoId };
  }
  return parsed;
}

function parseHostedAvatarImageUrl(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  if (!trimmed || trimmed.length > 2_048) return undefined;
  if (/^\/(?!\/)/.test(trimmed)) return trimmed;
  try {
    const url = new URL(trimmed);
    return url.protocol === "https:" ? url.toString() : undefined;
  } catch {
    return undefined;
  }
}

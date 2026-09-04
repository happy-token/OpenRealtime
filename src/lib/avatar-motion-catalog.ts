import type { AvatarRatio } from "@/components/digital-human/types";
import { readJsonResponse } from "./http-json-response";

export type AssetMedia = {
  duration_ms: number;
  width: number;
  height: number;
  video_codec: string;
  has_audio: boolean;
};

export type AvatarActionRendition = {
  rendition_id: string;
  profile: "mobile_fullscreen" | "desktop_fullscreen";
  phase: "queued" | "processing" | "ready_for_review" | "approved" | "failed";
  artifact_id?: string;
  media?: AssetMedia;
  failure_reason?: string;
};

export type AvatarActionAsset = {
  avatar_action_id: string;
  avatar_id: string;
  candidate_id: string;
  phase: "preparing" | "ready";
  source_master_artifact_id: string;
  source_media: AssetMedia;
  renditions: AvatarActionRendition[];
  created_at?: string;
};

export type AvatarActionSelection = {
  avatar_id: string;
  avatar_action_id: string;
  revision: number;
  selected_at?: string;
};

export type AvatarActionCatalog = {
  avatarActions: AvatarActionAsset[];
  selection: AvatarActionSelection | null;
};

export async function fetchAvatarActionCatalog(
  avatarId?: string,
  fetcher: typeof fetch = fetch,
  signal?: AbortSignal,
): Promise<AvatarActionCatalog> {
  const query = avatarId ? `?avatarId=${encodeURIComponent(avatarId)}` : "";
  const response = await fetcher(
    `/api/avatar-assets/actions${query}`,
    { cache: "no-store", signal },
  );
  const payload = await readJsonResponse<{
    actions?: unknown;
    selection?: unknown;
    error?: unknown;
  }>(response, "动作底片目录请求失败");
  if (!response.ok) {
    throw new Error(typeof payload.error === "string" ? payload.error : "动作底片目录读取失败");
  }
  if (!Array.isArray(payload.actions)) throw new Error("动作底片目录响应无效");
  return {
    avatarActions: payload.actions as AvatarActionAsset[],
    selection: payload.selection && typeof payload.selection === "object"
      ? payload.selection as AvatarActionSelection
      : null,
  };
}

export function selectAvatarActionRendition(
  action: AvatarActionAsset,
  ratio: AvatarRatio,
): { rendition: AvatarActionRendition; temporaryFit: boolean } | null {
  const approved = action.renditions.filter(
    (rendition) => rendition.phase === "approved" && Boolean(rendition.artifact_id),
  );
  if (!approved.length) return null;
  const desiredProfile = ratio === "9:16" ? "mobile_fullscreen" : "desktop_fullscreen";
  const exact = ratio === "1:1"
    ? undefined
    : approved.find((rendition) => rendition.profile === desiredProfile);
  return exact
    ? { rendition: exact, temporaryFit: false }
    : { rendition: approved.find((rendition) => rendition.profile === "desktop_fullscreen") ?? approved[0], temporaryFit: true };
}

export function avatarActionLabel(action: AvatarActionAsset): string {
  const date = action.created_at ? new Date(action.created_at) : null;
  const dateLabel = date && !Number.isNaN(date.valueOf())
    ? new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit" }).format(date)
    : "已验收";
  const profiles = action.renditions
    .filter((rendition) => rendition.phase === "approved")
    .map((rendition) => rendition.profile === "mobile_fullscreen" ? "9:16" : "16:9")
    .join(" + ");
  return `${dateLabel} 动作底片${profiles ? ` · ${profiles}` : ""}`;
}

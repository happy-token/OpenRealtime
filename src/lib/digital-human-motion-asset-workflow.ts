export type MotionAssetCandidate = {
  candidateId: string;
  artifactId: string;
  sourceKind: "liveportrait";
  phase: "candidate" | "accepting" | "accepted" | "failed";
  durationMs: number;
  width: number;
  height: number;
  videoCodec: string;
  hasAudio: boolean;
};

export type MotionAcceptanceCheckId =
  | "identity_match"
  | "single_person"
  | "closed_mouth"
  | "fixed_camera"
  | "no_gestures"
  | "rights_confirmed";

export type MotionAcceptanceChecks = Record<MotionAcceptanceCheckId, boolean>;

export type AvatarActionAsset = {
  avatarActionId: string;
  avatarId: string;
  candidateId: string;
  phase: "preparing" | "ready";
  sourceMasterArtifactId: string;
  durationMs: number;
  hasAudio: boolean;
  renditions: AvatarActionRendition[];
};

export type AvatarActionRendition = {
  renditionId: string;
  profile: "mobile_fullscreen" | "desktop_fullscreen";
  phase: "queued" | "processing" | "ready_for_review" | "approved" | "failed";
  artifactId?: string;
  durationMs?: number;
};

export type AvatarActionSelection = {
  avatarId: string;
  avatarActionId: string;
  revision: number;
};

export async function persistLivePortraitCandidate({
  taskId,
  avatarId,
  idempotencyKey,
  fetcher = fetch,
}: {
  taskId: string;
  avatarId: string;
  idempotencyKey: string;
  fetcher?: typeof fetch;
}): Promise<MotionAssetCandidate> {
  const response = await fetcher("/api/avatar-assets/candidates/provider", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sourceKind: "liveportrait",
      taskId,
      avatarId,
      idempotencyKey,
      rightsConfirmed: true,
    }),
  });
  const payload = await response.json() as {
    candidate_id?: unknown;
    artifact_id?: unknown;
    source_kind?: unknown;
    phase?: unknown;
    media?: {
      duration_ms?: unknown;
      width?: unknown;
      height?: unknown;
      video_codec?: unknown;
      has_audio?: unknown;
    };
    error?: unknown;
  };
  if (!response.ok) {
    throw new Error(typeof payload.error === "string" ? payload.error : "完整动作候选保存失败");
  }
  if (
    typeof payload.candidate_id !== "string"
    || typeof payload.artifact_id !== "string"
    || payload.source_kind !== "liveportrait"
    || !isCandidatePhase(payload.phase)
    || typeof payload.media?.duration_ms !== "number"
    || typeof payload.media.width !== "number"
    || typeof payload.media.height !== "number"
    || typeof payload.media.video_codec !== "string"
    || typeof payload.media.has_audio !== "boolean"
  ) {
    throw new Error("动作候选服务返回了无效数据");
  }
  return {
    candidateId: payload.candidate_id,
    artifactId: payload.artifact_id,
    sourceKind: payload.source_kind,
    phase: payload.phase,
    durationMs: payload.media.duration_ms,
    width: payload.media.width,
    height: payload.media.height,
    videoCodec: payload.media.video_codec,
    hasAudio: payload.media.has_audio,
  };
}

export async function acceptMotionCandidate({
  candidateId,
  idempotencyKey,
  checks,
  fetcher = fetch,
}: {
  candidateId: string;
  idempotencyKey: string;
  checks: MotionAcceptanceChecks;
  fetcher?: typeof fetch;
}): Promise<AvatarActionAsset> {
  if (!Object.values(checks).every(Boolean)) {
    throw new Error("请完成全部动作质量检查");
  }
  const response = await fetcher(`/api/avatar-assets/candidates/${encodeURIComponent(candidateId)}/accept`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ idempotencyKey, checks }),
  });
  const payload = await response.json() as Record<string, unknown> & { error?: unknown };
  if (!response.ok) {
    throw new Error(typeof payload.error === "string" ? payload.error : "动作候选验收入库失败");
  }
  return parseMotionBasePayload(payload);
}

export async function approveMotionRendition({
  renditionId,
  durationMs,
  fetcher = fetch,
}: {
  renditionId: string;
  durationMs: number;
  fetcher?: typeof fetch;
}): Promise<AvatarActionAsset> {
  const response = await fetcher(`/api/avatar-assets/renditions/${encodeURIComponent(renditionId)}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      startMs: 0,
      endMs: durationMs,
      crossfadeMs: Math.min(100, Math.floor(durationMs / 4)),
    }),
  });
  const payload = await response.json() as Record<string, unknown> & { error?: unknown };
  if (!response.ok) {
    throw new Error(typeof payload.error === "string" ? payload.error : "动作画幅审核失败");
  }
  return parseMotionBasePayload(payload);
}

export async function selectAvatarAction({
  avatarId,
  avatarActionId,
  fetcher = fetch,
}: {
  avatarId: string;
  avatarActionId: string;
  fetcher?: typeof fetch;
}): Promise<AvatarActionSelection> {
  const response = await fetcher("/api/avatar-assets/selections", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ avatarId, avatarActionId }),
  });
  const payload = await response.json() as {
    avatar_id?: unknown;
    avatar_action_id?: unknown;
    revision?: unknown;
    error?: unknown;
  };
  if (!response.ok) {
    throw new Error(typeof payload.error === "string" ? payload.error : "设为当前动作失败");
  }
  if (
    payload.avatar_id !== avatarId
    || payload.avatar_action_id !== avatarActionId
    || typeof payload.revision !== "number"
  ) {
    throw new Error("动作选择服务返回了无效数据");
  }
  return {
    avatarId: payload.avatar_id,
    avatarActionId: payload.avatar_action_id,
    revision: payload.revision,
  };
}

function isCandidatePhase(value: unknown): value is MotionAssetCandidate["phase"] {
  return value === "candidate" || value === "accepting" || value === "accepted" || value === "failed";
}

function parseMotionBasePayload(payload: Record<string, unknown>): AvatarActionAsset {
  const sourceMedia = payload.source_media as Record<string, unknown> | undefined;
  const rawRenditions = payload.renditions;
  if (
    typeof payload.avatar_action_id !== "string"
    || typeof payload.avatar_id !== "string"
    || typeof payload.candidate_id !== "string"
    || (payload.phase !== "preparing" && payload.phase !== "ready")
    || typeof payload.source_master_artifact_id !== "string"
    || typeof sourceMedia?.duration_ms !== "number"
    || typeof sourceMedia.has_audio !== "boolean"
    || !Array.isArray(rawRenditions)
  ) {
    throw new Error("动作资产服务返回了无效数据");
  }
  return {
    avatarActionId: payload.avatar_action_id,
    avatarId: payload.avatar_id,
    candidateId: payload.candidate_id,
    phase: payload.phase,
    sourceMasterArtifactId: payload.source_master_artifact_id,
    durationMs: sourceMedia.duration_ms,
    hasAudio: sourceMedia.has_audio,
    renditions: rawRenditions.map(parseRendition),
  };
}

function parseRendition(value: unknown): AvatarActionRendition {
  const rendition = value as Record<string, unknown> | null;
  const media = rendition?.media as Record<string, unknown> | undefined;
  if (
    !rendition
    || typeof rendition.rendition_id !== "string"
    || (rendition.profile !== "mobile_fullscreen" && rendition.profile !== "desktop_fullscreen")
    || !isRenditionPhase(rendition.phase)
    || (rendition.artifact_id != null && typeof rendition.artifact_id !== "string")
    || (media?.duration_ms != null && typeof media.duration_ms !== "number")
  ) {
    throw new Error("动作适配版本数据无效");
  }
  return {
    renditionId: rendition.rendition_id,
    profile: rendition.profile,
    phase: rendition.phase,
    artifactId: typeof rendition.artifact_id === "string" ? rendition.artifact_id : undefined,
    durationMs: typeof media?.duration_ms === "number" ? media.duration_ms : undefined,
  };
}

function isRenditionPhase(value: unknown): value is AvatarActionRendition["phase"] {
  return value === "queued"
    || value === "processing"
    || value === "ready_for_review"
    || value === "approved"
    || value === "failed";
}

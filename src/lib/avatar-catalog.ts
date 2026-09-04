export type AvatarVisibility = "private" | "shared";
export type AvatarActionState = "processing" | "needs-attention" | "available";
export type RealtimeBindingState = "creating" | "previewing" | "awaiting-acceptance" | "accepted" | "failed";

export interface AvatarRecord {
  avatar_id: string;
  display_name: string;
  owner_id: string | null;
  visibility: AvatarVisibility;
  source_image_url: string | null;
  provider_preview_url?: string | null;
  deleted_at?: string | null;
}

export interface AvatarActionRecord {
  avatar_action_id: string;
  avatar_id: string;
  display_name: string;
  state: AvatarActionState;
  video_url?: string | null;
  pending_model_count?: number;
  deleted_at?: string | null;
}

export interface AvatarRealtimeBindingRecord {
  provider_avatar_id: string;
  avatar_id: string;
  provider: "anam";
  avatar_model: string;
  state: RealtimeBindingState;
  preview_video_url?: string | null;
}

export type AvatarSource =
  | { kind: "owned"; imageUrl: string }
  | { kind: "provider-preview"; imageUrl: string };

export interface AvatarAction {
  avatarActionId: string;
  displayName: string;
  state: AvatarActionState;
  videoUrl: string | null;
  pendingModelCount: number;
}

export interface AvatarRealtimeBinding {
  providerAvatarId: string;
  provider: "anam";
  avatarModel: string;
  state: RealtimeBindingState;
  previewVideoUrl: string | null;
}

export interface AvatarAsset {
  avatarId: string;
  displayName: string;
  ownerId: string | null;
  visibility: AvatarVisibility;
  source: AvatarSource;
  actions: AvatarAction[];
  realtimeBinding: AvatarRealtimeBinding | null;
  canCreateActions: boolean;
  deletedAt: string | null;
}

export interface AvatarCatalogRecords {
  avatars: AvatarRecord[];
  actions: AvatarActionRecord[];
  realtime_bindings: AvatarRealtimeBindingRecord[];
}

export function buildAvatarCatalog(records: AvatarCatalogRecords): AvatarAsset[] {
  const actionsByAvatar = new Map<string, AvatarAction[]>();
  for (const action of records.actions) {
    if (action.deleted_at) continue;
    const actions = actionsByAvatar.get(action.avatar_id) ?? [];
    actions.push({
      avatarActionId: action.avatar_action_id,
      displayName: action.display_name,
      state: action.state,
      videoUrl: action.video_url ?? null,
      pendingModelCount: Math.max(0, action.pending_model_count ?? 0),
    });
    actionsByAvatar.set(action.avatar_id, actions);
  }

  const acceptedBindings = new Map<string, AvatarRealtimeBinding>();
  for (const binding of records.realtime_bindings) {
    if (binding.state !== "accepted") continue;
    acceptedBindings.set(binding.avatar_id, {
      providerAvatarId: binding.provider_avatar_id,
      provider: binding.provider,
      avatarModel: binding.avatar_model,
      state: binding.state,
      previewVideoUrl: binding.preview_video_url ?? null,
    });
  }

  return records.avatars.flatMap((record) => {
    const source = resolveAvatarSource(record);
    if (!source) return [];
    return [{
      avatarId: record.avatar_id,
      displayName: record.display_name,
      ownerId: record.owner_id,
      visibility: record.visibility,
      source,
      actions: actionsByAvatar.get(record.avatar_id) ?? [],
      realtimeBinding: acceptedBindings.get(record.avatar_id) ?? null,
      canCreateActions: source.kind === "owned",
      deletedAt: record.deleted_at ?? null,
    }];
  });
}

export function summarizeAvatarCapabilities(avatar: AvatarAsset) {
  const pendingActionCount = avatar.actions.filter((action) => (
    action.state !== "available" || action.pendingModelCount > 0
  )).length;
  return {
    imageLabel: avatar.source.kind === "owned" ? "可使用图片" : null,
    actionLabel: avatar.actions.length === 0 ? "尚未创建动作" : `${avatar.actions.length} 个动作`,
    pendingActionCount,
    realtimeLabel: avatar.realtimeBinding
      ? avatar.visibility === "shared" && avatar.source.kind === "provider-preview"
        ? "Anam 内置 · 仅实时驱动"
        : "实时驱动可用"
      : null,
  };
}

function resolveAvatarSource(record: AvatarRecord): AvatarSource | null {
  if (record.source_image_url) return { kind: "owned", imageUrl: record.source_image_url };
  if (record.provider_preview_url) {
    return { kind: "provider-preview", imageUrl: record.provider_preview_url };
  }
  return null;
}

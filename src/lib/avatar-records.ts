import type { AvatarRealtimeBindingRecord } from "./avatar-catalog";

export interface OwnedAvatarRecord {
  avatar_id: string;
  display_name: string;
  source_image_url: string;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  realtime_binding: AvatarRealtimeBindingRecord | null;
  actions: OwnedAvatarActionRecord[];
}

export interface OwnedAvatarActionRecord {
  avatar_action_id: string;
  display_name: string;
  video_url: string | null;
  pending_model_count: number;
  created_at: string;
  deleted_at: string | null;
}

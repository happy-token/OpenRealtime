import type { ConversationHistoryItem } from "./conversation-history";
import { avatarIdFromHostedRoleId } from "./hosted-avatar-role-id";

export function conversationContinuationUrl(item: ConversationHistoryItem): string | null {
  if (!item.thread_id || !item.voice_session_id) return null;
  const query = new URLSearchParams({ continue: item.id, role_mode: item.mode });
  const avatarId = item.role_id ? avatarIdFromHostedRoleId(item.role_id) : null;
  if (avatarId) query.set("realtime_avatar_id", avatarId);
  else query.set("role_id", item.role_id ?? "default-assistant");
  return `/conversation?${query}`;
}

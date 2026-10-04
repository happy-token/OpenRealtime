import { describe, expect, it } from "vitest";
import { conversationContinuationUrl } from "./conversation-continuation";
import type { ConversationHistoryItem } from "./conversation-history";
import { archiveTranscript, mergeAssistantTranscript } from "@/voice/session/transcript";

describe("history continuation", () => {
  const item: ConversationHistoryItem = { id: "history-id", owner_id: "alice", role_id: "role-one", role_name: "助手", mode: "conversation", title: "历史", started_at: "", updated_at: "", ended_at: null, entries: [], thread_id: "thread-one", voice_session_id: "voice-one" };
  it("routes ordinary and hosted roles and does not claim legacy records are resumable", () => {
    expect(conversationContinuationUrl(item)).toBe("/conversation?continue=history-id&role_mode=conversation&role_id=role-one");
    expect(conversationContinuationUrl({ ...item, role_id: "hosted-avatar-avatar-one" })).toContain("realtime_avatar_id=avatar-one");
    expect(conversationContinuationUrl({ ...item, thread_id: null })).toBeNull();
  });
  it("keeps historical answers when the new session reuses a generation number", () => {
    const history = archiveTranscript([{ role: "assistant", text: "old answer", generation: 1, status: "completed" }]);
    const result = mergeAssistantTranscript(history, 1, "new answer");
    expect(result.map((entry) => entry.text)).toEqual(["old answer", "new answer"]);
  });
});

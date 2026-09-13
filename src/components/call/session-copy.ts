import type { ConnectionState, ConversationState } from "@/hooks/use-voice-session";

export const SESSION_STATE_LABELS: Record<ConversationState, string> = {
  idle: "待命",
  listening: "我在听",
  thinking: "正在思考…",
  speaking: "正在回答",
};

export const CONNECTION_STATUS_LABELS: Partial<Record<ConnectionState, string>> = {
  connecting: "正在连接…",
  reconnecting: "连接中断，正在恢复…",
  error: "连接未恢复",
};

export function resolveSessionStatusLabel({
  state,
  microphoneMuted = false,
  ended = false,
}: {
  state: ConversationState;
  microphoneMuted?: boolean;
  ended?: boolean;
}) {
  if (ended) return "本次对话已结束";
  if (microphoneMuted) return "麦克风已关闭";
  return SESSION_STATE_LABELS[state];
}

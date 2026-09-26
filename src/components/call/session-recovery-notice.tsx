"use client";

import { AlertTriangle, Keyboard, RefreshCw } from "lucide-react";
import type { ConnectionState } from "@/hooks/use-voice-session";

interface SessionRecoveryNoticeProps {
  connection: ConnectionState;
  micError: string | null;
  micAvailable: boolean;
  sessionError: string | null;
  onRetryConnection: () => void;
  onRetryMicrophone: () => void;
  onUseText: () => void;
  voiceOnly?: boolean;
}

type RecoveryIssue = {
  kind: "connection" | "microphone" | "response";
  title: string;
  message: string;
  retryLabel?: string;
  retry: "connection" | "microphone" | null;
};

export function resolveSessionRecoveryIssue({ connection, micError, micAvailable, sessionError, voiceOnly }: Pick<SessionRecoveryNoticeProps, "connection" | "micError" | "micAvailable" | "sessionError" | "voiceOnly">): RecoveryIssue | null {
  if (voiceOnly && micError) return { kind: "response", title: "语音会话未开始", message: micError, retryLabel: "手动重试", retry: "microphone" };
  if (voiceOnly && connection === "error") return { kind: "connection", title: "语音连接失败", message: sessionError || "请手动重试语音会话。", retryLabel: "手动重试", retry: "microphone" };
  if (connection === "reconnecting") return { kind: "connection", title: "连接中断，正在恢复…", message: "输入的文字会保留，也可以立即重试。", retryLabel: "立即重试", retry: "connection" };
  if (connection === "error") return { kind: "connection", title: "连接未恢复", message: "请重试连接或改用文字，输入的草稿会保留。", retryLabel: "重试连接", retry: "connection" };
  if (sessionError) return { kind: "response", title: "本轮回复未完成", message: sessionError, retryLabel: "重新连接", retry: "connection" };
  if (micError) return { kind: "microphone", title: "麦克风无法使用", message: micError.replace(/^麦克风错误：/, ""), retryLabel: "重试麦克风", retry: "microphone" };
  if (connection === "open" && !micAvailable) return { kind: "microphone", title: "当前没有可用的语音输入", message: "你仍然可以继续使用文字对话，稍后也可以重新尝试麦克风。", retryLabel: "重试麦克风", retry: "microphone" };
  return null;
}

export function SessionRecoveryNotice(props: SessionRecoveryNoticeProps) {
  const issue = resolveSessionRecoveryIssue(props);
  if (!issue) return null;
  const retry = issue.retry === "connection" ? props.onRetryConnection : issue.retry === "microphone" ? props.onRetryMicrophone : null;
  return <section className="session-recovery-notice" data-kind={issue.kind} role="alert" aria-live="polite">
    <AlertTriangle aria-hidden="true" />
    <div className="session-recovery-copy"><strong>{issue.title}</strong><span>{issue.message}</span></div>
    <div className="session-recovery-actions">
      {retry && <button type="button" onClick={retry}><RefreshCw aria-hidden="true" />{issue.retryLabel}</button>}
      {!props.voiceOnly && <button type="button" onClick={props.onUseText}><Keyboard aria-hidden="true" />改用文字</button>}
    </div>
  </section>;
}

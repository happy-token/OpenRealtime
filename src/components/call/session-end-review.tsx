"use client";
import { useLanguage } from "@/components/language/language-provider";


import { ArrowLeft } from "lucide-react";
import type { TranscriptEntry } from "@/voice/session/transcript";
import { ConversationStartAction } from "./conversation-start-action";
import styles from "./session-end-review.module.css";

export interface SessionReviewSnapshot {
  endedAt: number;
  entries: TranscriptEntry[];
}

export function freezeSessionTranscript(entries: TranscriptEntry[]): TranscriptEntry[] {
  return entries
    .filter((entry) => entry.text.trim())
    .map((entry) => ({
      ...entry,
      status: entry.role === "assistant" && entry.status === "streaming"
        ? "interrupted"
        : entry.status,
    }));
}

interface SessionEndedActionsProps {
  connected: boolean;
  onContinue: () => void;
  onReturnHome: () => void;
}

export function SessionEndedActions({ connected, onContinue, onReturnHome }: SessionEndedActionsProps) {
  const { t } = useLanguage();
  return (
    <div className={styles.stageActions} aria-label={t("结束后的会话操作")}>
      <button type="button" className={styles.returnButton} onClick={onReturnHome}>
        <ArrowLeft aria-hidden="true" />{t("返回主页")}</button>
      <p className={styles.endedTitle}>{t("本次对话已结束")}</p>
      <ConversationStartAction
        connected={connected}
        onPress={onContinue}
        ariaLabel={t("继续对话")}
        label={t("继续对话")}
        hint=""
        className={styles.continueAction}
      />
    </div>
  );
}

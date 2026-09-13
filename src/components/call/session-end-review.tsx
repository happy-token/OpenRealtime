"use client";

import { ArrowLeft } from "lucide-react";
import type { TranscriptEntry } from "@/voice/session/transcript";
import { VoiceStartButton } from "@/components/ui/voice-start-button";
import type { PageForm } from "./presentation-model";
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
  pageForm: PageForm;
  onContinue: () => void;
  onReturnHome: () => void;
}

export function SessionEndedActions({ connected, pageForm, onContinue, onReturnHome }: SessionEndedActionsProps) {
  return (
    <div className={styles.stageActions} data-page-form={pageForm} aria-label="结束后的会话操作">
      <button type="button" className={styles.returnButton} onClick={onReturnHome}>
        <span><ArrowLeft aria-hidden="true" /></span>
        <strong>返回主页</strong>
      </button>
      <VoiceStartButton
        connected={connected}
        onPress={onContinue}
        ariaLabel="继续对话"
        label="继续对话"
        hint=""
      />
    </div>
  );
}

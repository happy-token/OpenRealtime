"use client";

import { VoiceStartButton } from "@/components/ui/voice-start-button";
import type { ReactNode } from "react";
import styles from "./preview-workspace-lab.module.css";

interface ConversationStartActionProps {
  connected: boolean;
  disabled?: boolean;
  ariaLabel: string;
  label: string;
  hint?: string;
  className?: string;
  children?: ReactNode;
  onPress: () => void;
}

export function ConversationStartAction({ connected, disabled, ariaLabel, label, hint, className, children, onPress }: ConversationStartActionProps) {
  return <div className={`${styles.homeStartAction}${className ? ` ${className}` : ""}`}>
    <VoiceStartButton
      effect="magic-rings"
      connected={connected}
      connectionStatusPlacement="external"
      disabled={disabled}
      ariaLabel={ariaLabel}
      label={label}
      hint={hint}
      onPress={onPress}
    />
    {children}
  </div>;
}

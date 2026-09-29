"use client";
import { useLanguage } from "@/components/language/language-provider";


import { useEffect, useRef } from "react";
import { useFocusTrap } from "@/hooks/use-focus-trap";
import type { PendingConfirmationView } from "@/hooks/use-voice-session";

interface ConfirmationCardProps {
  pending: PendingConfirmationView;
  onDecision: (approved: boolean) => void;
}

export function ConfirmationCard({ pending, onDecision }: ConfirmationCardProps) {
  const { t } = useLanguage();
  const dialogRef = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = dialogRef.current;
    const returnTarget = document.activeElement;
    dialog?.showModal();
    dialog?.querySelector<HTMLButtonElement>("button")?.focus();
    return () => {
      dialog?.close();
      if (returnTarget instanceof HTMLElement && returnTarget.isConnected) returnTarget.focus();
    };
  }, []);
  useFocusTrap(dialogRef, { active: true, onEscape: () => onDecision(false) });

  return (
    <dialog
      ref={dialogRef}
      onCancel={(event) => { event.preventDefault(); onDecision(false); }}
      className="confirmation-card"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="confirmation-title"
      aria-describedby="confirmation-summary"
    >
      <span className="confirmation-eyebrow">{t("需要你的确认")}</span>
      <h2 id="confirmation-title">{t("是否执行这项操作？")}</h2>
      <p id="confirmation-summary">{pending.summary}</p>
      {pending.requiredChannel === "strong" && (
        <small>{t("此操作需要更强的身份验证，当前语音会话不能批准。")}</small>
      )}
      <div className="confirmation-actions">
        <button type="button" onClick={() => onDecision(false)}>{t("拒绝")}</button>
        <button
          type="button"
          className="confirmation-approve"
          disabled={pending.requiredChannel === "strong"}
          onClick={() => onDecision(true)}
        >
          {t("确认执行")}</button>
      </div>
    </dialog>
  );
}

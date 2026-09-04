import type { PendingConfirmationView } from "@/hooks/use-voice-session";

interface ConfirmationCardProps {
  pending: PendingConfirmationView;
  onDecision: (approved: boolean) => void;
}

export function ConfirmationCard({ pending, onDecision }: ConfirmationCardProps) {
  return (
    <section
      className="confirmation-card"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="confirmation-title"
      aria-describedby="confirmation-summary"
    >
      <span className="confirmation-eyebrow">需要你的确认</span>
      <h2 id="confirmation-title">是否执行这项操作？</h2>
      <p id="confirmation-summary">{pending.summary}</p>
      {pending.requiredChannel === "strong" && (
        <small>此操作需要更强的身份验证，当前语音会话不能批准。</small>
      )}
      <div className="confirmation-actions">
        <button type="button" onClick={() => onDecision(false)}>拒绝</button>
        <button
          type="button"
          className="confirmation-approve"
          disabled={pending.requiredChannel === "strong"}
          onClick={() => onDecision(true)}
        >
          确认执行
        </button>
      </div>
    </section>
  );
}

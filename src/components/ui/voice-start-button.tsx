import { Mic } from "lucide-react";
import MagicRings from "./magic-rings";

interface VoiceStartButtonProps {
  connected: boolean;
  disabled?: boolean;
  onPress: () => void;
  label?: string;
  hint?: string;
  ariaLabel?: string;
  effect?: "halo" | "magic-rings";
  connectionStatusPlacement?: "inline" | "external";
}

export function VoiceStartButton({ connected, disabled = false, onPress, label, hint, ariaLabel, effect = "halo", connectionStatusPlacement = "inline" }: VoiceStartButtonProps) {
  const showInlineConnectionStatus = !connected && connectionStatusPlacement === "inline";
  const resolvedLabel = showInlineConnectionStatus ? "正在连接" : label ?? "开始语音对话";
  const resolvedHint = showInlineConnectionStatus ? "语音服务准备中…" : hint ?? (connected ? "轻触麦克风开始" : "");

  return (
    <div className="voice-start-halo-wrap">
      <button
        type="button"
        className={`voice-start-halo${effect === "magic-rings" ? " voice-start-halo--magic-rings" : ""}`}
        aria-label={ariaLabel ?? (connected ? "开始语音对话" : "正在连接语音服务")}
        disabled={!connected || disabled}
        onClick={onPress}
      >
        {effect === "magic-rings" ? <MagicRings /> : <>
          <span className="voice-start-halo-orbits" aria-hidden="true"><i /><i /><i /></span>
          <span className="voice-start-halo-nodes" aria-hidden="true"><i /><i /><i /></span>
        </>}
        <span className="voice-start-halo-core" aria-hidden="true">
          <span className="voice-start-halo-scan" />
          <Mic />
        </span>
      </button>
      <span className="voice-start-halo-copy" aria-live="polite">
        <strong>{resolvedLabel}</strong>
        {resolvedHint ? <small>{resolvedHint}</small> : null}
      </span>
    </div>
  );
}

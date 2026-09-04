import { Mic } from "lucide-react";

interface VoiceStartButtonProps {
  connected: boolean;
  disabled?: boolean;
  onPress: () => void;
  label?: string;
  hint?: string;
  ariaLabel?: string;
}

export function VoiceStartButton({ connected, disabled = false, onPress, label, hint, ariaLabel }: VoiceStartButtonProps) {
  const resolvedHint = connected ? hint ?? "轻触麦克风开始" : "语音服务准备中…";

  return (
    <div className="voice-start-halo-wrap">
      <button
        type="button"
        className="voice-start-halo"
        aria-label={ariaLabel ?? (connected ? "开始语音对话" : "正在连接语音服务")}
        disabled={!connected || disabled}
        onClick={onPress}
      >
        <span className="voice-start-halo-orbits" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>
        <span className="voice-start-halo-nodes" aria-hidden="true">
          <i />
          <i />
          <i />
        </span>
        <span className="voice-start-halo-core" aria-hidden="true">
          <span className="voice-start-halo-scan" />
          <Mic />
        </span>
      </button>
      <span className="voice-start-halo-copy" aria-live="polite">
        <strong>{connected ? label ?? "开始语音对话" : "正在连接"}</strong>
        {resolvedHint ? <small>{resolvedHint}</small> : null}
      </span>
    </div>
  );
}

import { Icon } from "./icons";

const CONNECTING_TITLE = "正在连接，请稍候…";

interface MicButtonProps {
  className: string;
  active: boolean;
  connected: boolean;
  onClick: () => void;
}

// Shared filled/pulse/disabled button used by both the call-dock main
// button and the chat inputbar mic button — both must stay in sync with
// the same engine.micActive state (this was the "chat mic icon doesn't
// reflect call-mode state" bug fixed pre-Next.js-port).
export function MicButton({ className, active, connected, onClick }: MicButtonProps) {
  const title = connected ? (active ? "结束语音对话" : "开始语音对话") : CONNECTING_TITLE;
  return (
    <button
      type="button"
      className={className}
      data-active={active ? "true" : "false"}
      disabled={!connected}
      title={title}
      aria-label={title}
      onClick={onClick}
    >
      <Icon name={active ? "stop" : "mic"} />
    </button>
  );
}

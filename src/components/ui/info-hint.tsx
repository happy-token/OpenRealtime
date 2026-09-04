import { CircleHelp } from "lucide-react";

interface InfoHintProps {
  text: string;
}

export function InfoHint({ text }: InfoHintProps) {
  return (
    <span className="inline-info-hint" tabIndex={0} aria-label={`帮助：${text}`} data-tooltip={text}>
      <CircleHelp aria-hidden="true" />
    </span>
  );
}

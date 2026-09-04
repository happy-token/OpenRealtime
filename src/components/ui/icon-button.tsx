import { Icon, type IconName } from "./icons";

interface IconButtonProps {
  icon: IconName;
  label: string;
  onClick: () => void;
  className?: string;
}

export function IconButton({ icon, label, onClick, className }: IconButtonProps) {
  return (
    <button
      type="button"
      className={`icon-btn ${className ?? ""}`}
      title={label}
      aria-label={label}
      onClick={onClick}
    >
      <Icon name={icon} />
    </button>
  );
}

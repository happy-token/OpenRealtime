// Inline icon paths ported verbatim from clients/web/ui.js's ICONS map.

export type IconName =
  | "mic"
  | "stop"
  | "keyboard"
  | "gear"
  | "send"
  | "list"
  | "arrow-left"
  | "expand"
  | "chat"
  | "pause"
  | "play"
  | "power";

const ICON_PATHS: Record<IconName, string> = {
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3M9 21h6"/>',
  stop: '<rect x="7" y="7" width="10" height="10" rx="2"/>',
  keyboard:
    '<rect x="3" y="6" width="18" height="12" rx="2"/><path d="M6 10h1M10 10h1M14 10h1M18 10h1M6 14h9"/>',
  gear:
    '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.9l-1.42 1.4a1.7 1.7 0 0 0-1.9-.33 1.7 1.7 0 0 0-1 1.55v2H10.6v-2a1.7 1.7 0 0 0-1-1.55 1.7 1.7 0 0 0-1.9.33l-1.42-1.4a1.7 1.7 0 0 0 .34-1.9A1.7 1.7 0 0 0 5 13.4H3v-2.8h2a1.7 1.7 0 0 0 1.55-1A1.7 1.7 0 0 0 6.2 7.7L7.63 6.3a1.7 1.7 0 0 0 1.9.34A1.7 1.7 0 0 0 10.6 5V3h2.8v2a1.7 1.7 0 0 0 1 1.55 1.7 1.7 0 0 0 1.9-.34l1.42 1.4a1.7 1.7 0 0 0-.34 1.9 1.7 1.7 0 0 0 1.55 1h2v2.8h-2a1.7 1.7 0 0 0-1.55 1"/>',
  send: '<path d="M4 12l16-7-6 16-2-7-8-2Z"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  "arrow-left": '<path d="m15 18-6-6 6-6M9 12h11"/>',
  expand: '<path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"/>',
  chat: '<path d="M21 12a8 8 0 0 1-8 8H5l-3 2 1-5a8 8 0 1 1 18-5Z"/>',
  pause: '<path d="M9 5v14M15 5v14"/>',
  play: '<path d="m8 5 11 7-11 7Z"/>',
  power: '<path d="M12 2v10M18.4 5.6a9 9 0 1 1-12.8 0"/>',
};

interface IconProps {
  name: IconName;
  className?: string;
}

export function Icon({ name, className }: IconProps) {
  return (
    <svg
      className={`icon ${className ?? ""}`}
      viewBox="0 0 24 24"
      // Fixed internal icon paths, no user input ever flows into this.
      dangerouslySetInnerHTML={{ __html: ICON_PATHS[name] }}
    />
  );
}

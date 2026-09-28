"use client";

import {
  useState,
  type CSSProperties,
  type FocusEvent,
  type PointerEvent,
  type ReactNode,
} from "react";
import styles from "./folder.module.css";

type FolderStyle = CSSProperties & {
  "--folder-color": string;
  "--folder-back-color": string;
  "--folder-scale": number;
};

type PaperStyle = CSSProperties & {
  "--magnet-x": string;
  "--magnet-y": string;
  "--paper-x": string;
  "--paper-y": string;
  "--paper-rotate": string;
  "--paper-z": number;
  "--stack-x": string;
  "--stack-y": string;
  "--stack-rotate": string;
};

interface FolderProps {
  ariaLabel: string;
  front: ReactNode;
  frontClassName?: string;
  frontSelected?: boolean;
  items?: ReactNode[];
  itemAriaLabels?: string[];
  selectedItemIndex?: number;
  color?: string;
  size?: number;
  className?: string;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  onFrontClick?: () => boolean | void;
  onFrontPointerDown?: (event: PointerEvent<HTMLButtonElement>) => void;
  onFrontPointerMove?: (event: PointerEvent<HTMLButtonElement>) => void;
  onFrontPointerUp?: (event: PointerEvent<HTMLButtonElement>) => void;
  onFrontPointerCancel?: (event: PointerEvent<HTMLButtonElement>) => void;
  onFrontPointerEnter?: (event: PointerEvent<HTMLButtonElement>) => void;
  onFrontPointerLeave?: (event: PointerEvent<HTMLButtonElement>) => void;
  onFrontFocus?: (event: FocusEvent<HTMLButtonElement>) => void;
  onFrontBlur?: (event: FocusEvent<HTMLButtonElement>) => void;
  onItemSelect?: (index: number) => void;
}

function darkenColor(hex: string, percent: number) {
  let color = hex.startsWith("#") ? hex.slice(1) : hex;
  if (color.length === 3) color = color.split("").map((character) => character + character).join("");
  const numeric = Number.parseInt(color.slice(0, 6), 16);
  if (!Number.isFinite(numeric)) return "#4D7468";
  const channel = (shift: number) => Math.max(0, Math.min(255, Math.floor(((numeric >> shift) & 0xff) * (1 - percent))));
  return `#${[channel(16), channel(8), channel(0)].map((value) => value.toString(16).padStart(2, "0")).join("")}`;
}

export default function Folder({
  ariaLabel,
  front,
  frontClassName = "",
  frontSelected = false,
  items = [],
  itemAriaLabels = [],
  selectedItemIndex = -1,
  color = "#8ED9BF",
  size = 1,
  className = "",
  open: controlledOpen,
  onOpenChange,
  onFrontClick,
  onFrontPointerDown,
  onFrontPointerMove,
  onFrontPointerUp,
  onFrontPointerCancel,
  onFrontPointerEnter,
  onFrontPointerLeave,
  onFrontFocus,
  onFrontBlur,
  onItemSelect,
}: FolderProps) {
  const [internalOpen, setInternalOpen] = useState(false);
  const [paperOffsets, setPaperOffsets] = useState<Record<number, { x: number; y: number }>>({});
  const open = controlledOpen ?? internalOpen;
  const papers = items;
  const style = {
    "--folder-color": color,
    "--folder-back-color": darkenColor(color, .2),
    "--folder-scale": size,
  } as FolderStyle;

  const toggle = () => {
    if (onFrontClick?.() === false) return;
    const nextOpen = !open;
    if (controlledOpen === undefined) setInternalOpen(nextOpen);
    if (!nextOpen) setPaperOffsets({});
    onOpenChange?.(nextOpen);
  };

  const movePaper = (event: PointerEvent<HTMLButtonElement>, index: number) => {
    if (!open) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const x = (event.clientX - rect.left - rect.width / 2) * .15;
    const y = (event.clientY - rect.top - rect.height / 2) * .15;
    setPaperOffsets((current) => ({ ...current, [index]: { x, y } }));
  };

  const resetPaper = (index: number) => {
    setPaperOffsets((current) => ({ ...current, [index]: { x: 0, y: 0 } }));
  };

  return (
    <div className={`${styles.root} ${className}`} data-open={open} data-selected={frontSelected} style={style}>
      <div className={styles.folder}>
        <div className={styles.back} aria-hidden="true" />
        {papers.map((item, index) => {
          const centerOffset = index - (papers.length - 1) / 2;
          const spacing = papers.length > 1 ? Math.min(82, 260 / (papers.length - 1)) : 0;
          const normalizedDistance = papers.length > 1 ? Math.abs(centerOffset) / ((papers.length - 1) / 2) : 0;
          return (
          <button
            className={styles.paper}
            key={itemAriaLabels[index] ?? index}
            type="button"
            data-selected={selectedItemIndex === index}
            aria-label={itemAriaLabels[index] ?? `选择素材 ${index + 1}`}
            aria-pressed={selectedItemIndex === index}
            aria-hidden={!open}
            tabIndex={open ? 0 : -1}
            style={{
              "--magnet-x": `${paperOffsets[index]?.x ?? 0}px`,
              "--magnet-y": `${paperOffsets[index]?.y ?? 0}px`,
              "--paper-x": `${centerOffset * spacing}px`,
              "--paper-y": `${-92 - (1 - normalizedDistance) * 26}px`,
              "--paper-rotate": `${centerOffset * Math.min(7, 18 / Math.max(1, papers.length - 1))}deg`,
              "--paper-z": index + 2,
              "--stack-x": `${centerOffset * 2}px`,
              "--stack-y": `${-7 - index * 3}px`,
              "--stack-rotate": `${centerOffset * 1.4}deg`,
            } as PaperStyle}
            onPointerMove={(event) => movePaper(event, index)}
            onPointerLeave={() => resetPaper(index)}
            onClick={(event) => {
              event.stopPropagation();
              onItemSelect?.(index);
            }}
          >
            {item}
          </button>
          );
        })}
        <button
          className={`${styles.front} ${frontClassName}`}
          type="button"
          data-selected={frontSelected}
          aria-label={ariaLabel}
          aria-expanded={open}
          onPointerEnter={onFrontPointerEnter}
          onPointerLeave={onFrontPointerLeave}
          onPointerDown={onFrontPointerDown}
          onPointerMove={onFrontPointerMove}
          onPointerUp={onFrontPointerUp}
          onPointerCancel={onFrontPointerCancel}
          onFocus={onFrontFocus}
          onBlur={onFrontBlur}
          onClick={toggle}
        >
          {front}
        </button>
        <span className={styles.fold} aria-hidden="true" />
      </div>
    </div>
  );
}

"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import styles from "./line-sidebar.module.css";

const FALLOFF_CURVES = {
  linear: (p: number) => p,
  smooth: (p: number) => p * p * (3 - 2 * p),
  sharp: (p: number) => p * p * p,
};

export type LineSidebarItem = {
  id: string;
  label: string;
  ariaLabel?: string;
  href?: string;
  onClick?: () => void;
  disabled?: boolean;
  icon?: ReactNode;
  tone?: "danger";
};

type LineSidebarProps = {
  items: LineSidebarItem[];
  accentColor?: string;
  textColor?: string;
  markerColor?: string;
  showIndex?: boolean;
  showMarker?: boolean;
  proximityRadius?: number;
  maxShift?: number;
  falloff?: keyof typeof FALLOFF_CURVES;
  markerLength?: number;
  markerGap?: number;
  tickScale?: number;
  scaleTick?: boolean;
  itemGap?: number;
  fontSize?: number;
  smoothing?: number;
  defaultActive?: number | null;
  activeIndex?: number | null;
  onItemClick?: (index: number, label: string) => void;
  className?: string;
  ariaLabel?: string;
};

export default function LineSidebar({
  items,
  accentColor = "#A855F7",
  textColor = "#c4c4c4",
  markerColor = "#6c6c6c",
  showIndex = true,
  showMarker = true,
  proximityRadius = 100,
  maxShift = 30,
  falloff = "smooth",
  markerLength = 60,
  markerGap = 0,
  tickScale = 0.5,
  scaleTick = true,
  itemGap = 20,
  fontSize = 1.1,
  smoothing = 100,
  defaultActive = null,
  activeIndex,
  onItemClick,
  className = "",
  ariaLabel = "选项",
}: LineSidebarProps) {
  const listRef = useRef<HTMLUListElement>(null);
  const itemRefs = useRef<Array<HTMLLIElement | null>>([]);
  const targetsRef = useRef<number[]>([]);
  const currentRef = useRef<number[]>([]);
  const rafRef = useRef<number | null>(null);
  const lastRef = useRef(0);
  const activeRef = useRef<number | null>(defaultActive);
  const smoothingRef = useRef(smoothing);
  const [internalActive, setInternalActive] = useState(defaultActive);
  const selectedIndex = activeIndex === undefined ? internalActive : activeIndex;

  activeRef.current = selectedIndex;
  smoothingRef.current = smoothing;

  const runFrame = useCallback((now: number) => {
    const dt = Math.min((now - lastRef.current) / 1000, 0.05);
    lastRef.current = now;
    const tau = Math.max(smoothingRef.current, 1) / 1000;
    const k = 1 - Math.exp(-dt / tau);
    let moving = false;

    for (let i = 0; i < itemRefs.current.length; i++) {
      const element = itemRefs.current[i];
      if (!element) continue;
      const target = Math.max(targetsRef.current[i] || 0, activeRef.current === i ? 1 : 0);
      const next = (currentRef.current[i] || 0) + (target - (currentRef.current[i] || 0)) * k;
      const settled = Math.abs(target - next) < 0.0015;
      const value = settled ? target : next;
      currentRef.current[i] = value;
      element.style.setProperty("--effect", value.toFixed(4));
      if (!settled) moving = true;
    }

    rafRef.current = moving ? requestAnimationFrame(runFrame) : null;
  }, []);

  const startLoop = useCallback(() => {
    if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    lastRef.current = performance.now();
    rafRef.current = requestAnimationFrame(runFrame);
  }, [runFrame]);

  const handlePointerMove = useCallback((event: React.PointerEvent<HTMLUListElement>) => {
    const list = listRef.current;
    if (!list) return;
    const rect = list.getBoundingClientRect();
    const pointerY = event.clientY - rect.top;
    const ease = FALLOFF_CURVES[falloff];
    for (let i = 0; i < itemRefs.current.length; i++) {
      const element = itemRefs.current[i];
      if (!element) continue;
      const bounds = element.getBoundingClientRect();
      const center = bounds.top - rect.top + bounds.height / 2;
      targetsRef.current[i] = ease(Math.max(0, 1 - Math.abs(pointerY - center) / proximityRadius));
    }
    startLoop();
  }, [falloff, proximityRadius, startLoop]);

  const handlePointerLeave = useCallback(() => {
    targetsRef.current = targetsRef.current.map(() => 0);
    startLoop();
  }, [startLoop]);

  useEffect(() => { startLoop(); }, [selectedIndex, items.length, startLoop]);
  useEffect(() => () => {
    if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
  }, []);

  const variables = {
    "--accent-color": accentColor,
    "--text-color": textColor,
    "--marker-color": markerColor,
    "--marker-length": `${markerLength}px`,
    "--marker-gap": `${markerGap}px`,
    "--tick-scale": tickScale,
    "--max-shift": `${maxShift}px`,
    "--item-gap": `${itemGap}px`,
    "--font-size": `${fontSize}rem`,
  } as CSSProperties;

  return <nav
    className={`${styles.sidebar} ${showMarker ? styles.markers : ""} ${scaleTick ? styles.scaleTick : ""} ${className}`}
    style={variables}
    aria-label={ariaLabel}
  >
    <ul ref={listRef} className={styles.list} onPointerMove={handlePointerMove} onPointerLeave={handlePointerLeave}>
      {items.map((item, index) => {
        const content = <>
          {item.icon ? <span className={styles.icon} aria-hidden="true">{item.icon}</span> : null}
          {showIndex ? <span className={styles.index}>{String(index + 1).padStart(2, "0")}</span> : null}
          <span className={styles.text}>{item.label}</span>
        </>;
        return <li
          key={item.id}
          ref={element => { itemRefs.current[index] = element; }}
          className={`${styles.item} ${item.tone === "danger" ? styles.danger : ""}`}
        >
          {showMarker ? <span className={styles.marker} aria-hidden="true" /> : null}
          {item.href ? <Link className={styles.label} href={item.href} aria-label={item.ariaLabel} title={item.label}>{content}</Link>
            : <button
              className={styles.label}
              type="button"
              aria-label={item.ariaLabel}
              aria-pressed={onItemClick ? selectedIndex === index : undefined}
              title={item.label}
              disabled={item.disabled}
              onClick={() => {
                if (onItemClick) {
                  if (activeIndex === undefined) setInternalActive(index);
                  onItemClick(index, item.label);
                } else item.onClick?.();
              }}
            >{content}</button>}
        </li>;
      })}
    </ul>
  </nav>;
}

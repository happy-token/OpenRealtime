"use client";

import { useEffect, useRef, type RefObject } from "react";

export const FOCUS_TRAP_SELECTOR =
  "button:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex='-1'])";

export function resolveFocusTrapWrapTarget(
  activeElement: unknown,
  first: unknown,
  last: unknown,
  shiftKey: boolean,
): unknown | null {
  if (shiftKey && activeElement === first) return last;
  if (!shiftKey && activeElement === last) return first;
  return null;
}

interface UseFocusTrapOptions {
  active: boolean;
  onEscape?: () => void;
  returnFocusRef?: RefObject<HTMLElement | null>;
}

export function useFocusTrap(
  containerRef: RefObject<HTMLElement | null>,
  { active, onEscape, returnFocusRef }: UseFocusTrapOptions,
): void {
  const onEscapeRef = useRef(onEscape);

  useEffect(() => {
    onEscapeRef.current = onEscape;
  });

  useEffect(() => {
    if (!active) return;

    const returnTarget = returnFocusRef?.current
      ?? (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    const container = containerRef.current;
    const focusable = container
      ? Array.from(container.querySelectorAll<HTMLElement>(FOCUS_TRAP_SELECTOR))
      : [];
    focusable[0]?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onEscapeRef.current?.();
        return;
      }
      if (event.key !== "Tab" || !containerRef.current) return;
      const current = Array.from(
        containerRef.current.querySelectorAll<HTMLElement>(FOCUS_TRAP_SELECTOR),
      );
      if (!current.length) return;
      const first = current[0];
      const last = current[current.length - 1];
      const target = resolveFocusTrapWrapTarget(
        document.activeElement,
        first,
        last,
        event.shiftKey,
      );
      if (target) {
        event.preventDefault();
        (target as HTMLElement).focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      if (returnTarget?.isConnected) returnTarget.focus();
    };
  }, [active, containerRef, returnFocusRef]);
}

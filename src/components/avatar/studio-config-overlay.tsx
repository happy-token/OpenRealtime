"use client";
import { useLanguage } from "@/components/language/language-provider";


import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { X } from "lucide-react";
import { useBodyScrollLock } from "@/hooks/use-body-scroll-lock";
import { useFocusTrap } from "@/hooks/use-focus-trap";
import styles from "./studio-config-overlay.module.css";

const NARROW_VIEWPORT_QUERY = "(max-width: 699px)";

interface StudioConfigOverlayProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  label: string;
  icon: ReactNode;
  children: ReactNode;
}

export function StudioConfigOverlay({ open, onOpenChange, label, icon, children }: StudioConfigOverlayProps) {
  const { t } = useLanguage();
  const [isNarrow, setIsNarrow] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const dialogId = useId();

  useEffect(() => {
    const media = window.matchMedia(NARROW_VIEWPORT_QUERY);
    const syncNarrow = () => setIsNarrow(media.matches);
    syncNarrow();
    media.addEventListener("change", syncNarrow);
    return () => media.removeEventListener("change", syncNarrow);
  }, []);

  useEffect(() => {
    if (!isNarrow && open) onOpenChange(false);
  }, [isNarrow, open, onOpenChange]);

  const isOpen = isNarrow && open;
  useBodyScrollLock(isOpen);
  useFocusTrap(panelRef, {
    active: isOpen,
    onEscape: () => onOpenChange(false),
    returnFocusRef: toggleRef,
  });

  if (!isNarrow) return <>{children}</>;

  return (
    <>
      <button
        className={styles.backdrop}
        type="button"
        aria-label={t("关闭") + (label) + ""}
        data-open={isOpen}
        onClick={() => onOpenChange(false)}
      />
      <div
        ref={panelRef}
        className={styles.panel}
        data-open={isOpen}
        id={dialogId}
        role={isOpen ? "dialog" : undefined}
        aria-modal={isOpen ? true : undefined}
        aria-label={isOpen ? label : undefined}
      >
        {isOpen ? (
          <>
            <header className={styles.panelHeader}>
              <span className={styles.panelHeaderIcon}>{icon}</span>
              <strong>{t(label)}</strong>
              <button
                ref={toggleRef}
                type="button"
                aria-label={t("收起") + (label) + ""}
                aria-expanded={true}
                aria-controls={dialogId}
                onClick={() => onOpenChange(false)}
              >
                <X aria-hidden="true" />
              </button>
            </header>
            <div className={styles.panelBody}>{children}</div>
          </>
        ) : (
          <button
            ref={toggleRef}
            className={styles.toggle}
            type="button"
            aria-label={label}
            aria-expanded={false}
            aria-controls={dialogId}
            onClick={() => onOpenChange(true)}
          >
            {icon}
          </button>
        )}
      </div>
    </>
  );
}

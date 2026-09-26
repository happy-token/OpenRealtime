"use client";

import { X } from "lucide-react";
import { useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { HomeBackdrop } from "./home-backdrop";
import styles from "./workspace-overlay.module.css";

export function WorkspaceOverlay({ children, label }: { children: ReactNode; label: string }) {
  const router = useRouter();

  return <section className={styles.overlay} aria-label={label} data-workspace-overlay="true">
    <HomeBackdrop overlay />
    <button className={styles.backdrop} type="button" aria-label="关闭页面" onClick={() => router.back()} />
    <div className={styles.panel} data-page-glass="true">
      <button className={styles.closeButton} type="button" aria-label="关闭页面" onClick={() => router.back()}><X /></button>
      <div className={styles.content}>{children}</div>
    </div>
  </section>;
}

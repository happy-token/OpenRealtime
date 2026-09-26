"use client";

import Link from "next/link";
import { useAvatarCapabilities } from "@/hooks/use-avatar-capabilities";
import { AvatarCapabilityNotice } from "./avatar-capability-notice";
import { ArrowLeft } from "lucide-react";
import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import {
  DEFAULT_WORKBENCH_VISUAL_PREFERENCES,
  readWorkbenchVisualPreferences,
  WORKBENCH_VISUAL_PREFERENCES_EVENT,
  workbenchSurfaceTokens,
} from "@/lib/workbench-visual-preferences";
import { AvatarSceneBackground } from "./avatar-scene-background";
import styles from "./avatar-page-shell.module.css";

export type AvatarPageDestination = "library" | "create" | "personas";
export type AvatarPageBackDestination = {
  href: string;
  label: string;
};

export function AvatarPageShell({
  active,
  back = { href: "/", label: "返回主页" },
  pageTitle,
  hideNavigation = false,
  children,
}: {
  active: AvatarPageDestination;
  back?: AvatarPageBackDestination;
  pageTitle?: string;
  hideNavigation?: boolean;
  children: ReactNode;
}) {
  const { capabilities, error, retry } = useAvatarCapabilities();
  const [preferences, setPreferences] = useState(DEFAULT_WORKBENCH_VISUAL_PREFERENCES);
  useEffect(() => {
    const sync = () => setPreferences(readWorkbenchVisualPreferences());
    sync();
    window.addEventListener("storage", sync);
    window.addEventListener(WORKBENCH_VISUAL_PREFERENCES_EVENT, sync);
    return () => {
      window.removeEventListener("storage", sync);
      window.removeEventListener(WORKBENCH_VISUAL_PREFERENCES_EVENT, sync);
    };
  }, []);
  const tokens = workbenchSurfaceTokens(preferences);
  const surfaceStyle = {
    "--panel-surface-alpha": tokens.surfaceAlpha,
    "--panel-highlight-alpha": tokens.highlightAlpha,
    "--panel-soft-alpha": tokens.softAlpha,
    "--panel-blur": tokens.blur,
  } as CSSProperties;

  return (
    <div className={styles.shell} style={surfaceStyle}>
      <AvatarSceneBackground />
      <div className={styles.ambientTwo} aria-hidden="true" />
      <div className={styles.grain} aria-hidden="true" />
      <header className={styles.topbar}>
        <div className={styles.identity}>
          <Link className={styles.back} href={back.href} aria-label={back.label}><ArrowLeft aria-hidden="true" /></Link>
          {pageTitle ? <h1 className={styles.pageTitle}>{pageTitle}</h1> : null}
        </div>
        {!hideNavigation ? <nav className={styles.nav} aria-label="Avatar 页面">
          <span className={styles.navTrack} data-active={active} aria-hidden="true" />
          <Link href="/resources?tab=avatars" data-active={active === "library"}>资产管理</Link>
          <Link href="/avatars/create" data-active={active === "create"}>创建数字人</Link>
          <Link href="/personas" data-active={active === "personas"}>Persona 库</Link>
        </nav> : null}
        <span className={styles.wordmark}>OPENREALTIME</span>
      </header>
      <main className={styles.main}>
        {(error || capabilities?.assets.state !== "available") && <AvatarCapabilityNotice capability={capabilities?.assets} error={error} onRetry={retry} />}
        {children}
      </main>
    </div>
  );
}

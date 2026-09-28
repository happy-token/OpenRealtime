"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { Orb } from "@/components/call/orb";
import { isVoiceVisualTheme, type VoiceVisualTheme } from "@/components/call/voice-theme";
import styles from "./home-backdrop.module.css";

const STORAGE_KEY = "openrealtime-home-backdrop-v1";
const CHANGE_EVENT = "openrealtime:home-backdrop-changed";

export type HomeBackdropScene = {
  mode: "avatar" | "voice";
  image?: string;
  theme?: VoiceVisualTheme;
};

const DEFAULT_SCENE: HomeBackdropScene = {
  mode: "avatar",
};

function safeImage(value: unknown) {
  if (typeof value !== "string") return undefined;
  if (value.split(/[?#]/)[0].endsWith("/digital-human/shuchang-preview.jpg")) return undefined;
  if (value.startsWith("/") && !value.startsWith("//")) return value;
  if (/^https?:\/\//i.test(value)) return value;
  return undefined;
}

function readScene(): HomeBackdropScene {
  try {
    const stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "null") as Partial<HomeBackdropScene> | null;
    if (!stored || (stored.mode !== "avatar" && stored.mode !== "voice")) return DEFAULT_SCENE;
    return {
      mode: stored.mode,
      image: safeImage(stored.image),
      theme: isVoiceVisualTheme(stored.theme ?? null) ? stored.theme : "cloud",
    };
  } catch {
    return DEFAULT_SCENE;
  }
}

export function publishHomeBackdropScene(scene: HomeBackdropScene) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...scene, image: safeImage(scene.image) }));
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

/** Workspace pages share the selected home scene without a built-in avatar fallback. */
export function HomeBackdrop({ overlay = false }: { overlay?: boolean }) {
  const pathname = usePathname();
  const [scene, setScene] = useState<HomeBackdropScene>(DEFAULT_SCENE);

  useEffect(() => {
    const sync = () => setScene(readScene());
    sync();
    window.addEventListener(CHANGE_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(CHANGE_EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  return <div className={styles.backdrop} data-home-backdrop="true" data-overlay={overlay} data-mode={scene.mode === "avatar" && !scene.image ? "neutral" : scene.mode} aria-hidden="true">
    {pathname !== "/conversation" && scene.mode === "avatar" && scene.image ? <>
      <div className={styles.imageBlur} style={{ backgroundImage: `url(${JSON.stringify(scene.image)})` }} />
      <div className={styles.image} style={{ backgroundImage: `url(${JSON.stringify(scene.image)})` }} />
    </> : scene.mode === "voice" ? <div className={styles.voicePreview}>{pathname !== "/conversation" ? <Orb state="listening" level={0.22} theme={scene.theme ?? "cloud"} /> : null}</div> : null}
    <div className={styles.wash} />
  </div>;
}

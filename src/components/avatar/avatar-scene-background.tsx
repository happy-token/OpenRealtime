"use client";

import Image from "next/image";
import { useEffect, useState } from "react";
import {
  DEFAULT_AVATAR_DISPLAY_CONFIG,
  parseAvatarDisplayConfig,
  parseExperienceMode,
  type AvatarDisplayConfig,
  type ExperienceMode,
} from "@/components/digital-human/types";
import {
  AVATAR_DISPLAY_CONFIG_STORAGE_KEY,
  EXPERIENCE_MODE_STORAGE_KEY,
} from "@/lib/avatar-identity-sync";
import { loadCurrentAvatarCatalog } from "@/lib/avatar-library-catalog-client";
import {
  resolveMainScreenAvatarBackground,
  shouldBypassAvatarSceneImageOptimization,
  type AvatarSceneBackground,
} from "@/lib/avatar-scene-background";
import styles from "./avatar-page-shell.module.css";

export function AvatarSceneBackground() {
  const [background, setBackground] = useState<AvatarSceneBackground | null>(null);
  const [unavailableImageUrl, setUnavailableImageUrl] = useState<string | null>(null);
  const [unavailableVideoUrl, setUnavailableVideoUrl] = useState<string | null>(null);
  const [motionReduced, setMotionReduced] = useState(false);

  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const syncMotionPreference = () => setMotionReduced(media.matches);
    syncMotionPreference();
    media.addEventListener("change", syncMotionPreference);
    return () => media.removeEventListener("change", syncMotionPreference);
  }, []);

  useEffect(() => {
    let activeController: AbortController | null = null;
    let revision = 0;

    async function syncFromMainScreen() {
      const currentRevision = ++revision;
      activeController?.abort();
      const controller = new AbortController();
      activeController = controller;
      const { experienceMode, config } = readMainScreenScene();
      const avatars = experienceMode === "avatar" && config.renderPath === "segmented"
        ? await loadCurrentAvatarCatalog(controller.signal, { includeHostedAvatars: false }).catch(() => [])
        : [];
      if (currentRevision !== revision || controller.signal.aborted) return;
      setUnavailableImageUrl(null);
      setUnavailableVideoUrl(null);
      setBackground(resolveMainScreenAvatarBackground(experienceMode, config, avatars));
    }

    void syncFromMainScreen();
    const syncStoredConfig = (event: StorageEvent) => {
      if (event.key === AVATAR_DISPLAY_CONFIG_STORAGE_KEY || event.key === EXPERIENCE_MODE_STORAGE_KEY) {
        void syncFromMainScreen();
      }
    };
    window.addEventListener("storage", syncStoredConfig);
    return () => {
      revision += 1;
      activeController?.abort();
      window.removeEventListener("storage", syncStoredConfig);
    };
  }, []);

  const sceneVideoUrl = !motionReduced && background?.videoUrl !== unavailableVideoUrl
    ? background?.videoUrl ?? null
    : null;
  const sceneImageUrl = background?.imageUrl !== unavailableImageUrl
    ? background?.imageUrl ?? null
    : null;

  return (
    <div
      className={styles.sceneBackground}
      data-scene-key={background?.sceneKey ?? "none"}
      data-media={sceneVideoUrl ? "video" : sceneImageUrl ? "image" : "fallback"}
      aria-hidden="true"
    >
      {sceneImageUrl ? (
        <Image
          key={`${background?.sceneKey ?? sceneImageUrl}:image`}
          className={styles.sceneImage}
          src={sceneImageUrl}
          alt=""
          fill
          priority
          sizes="100vw"
          unoptimized={shouldBypassAvatarSceneImageOptimization(sceneImageUrl)}
          onError={() => setUnavailableImageUrl(sceneImageUrl)}
        />
      ) : null}
      {sceneVideoUrl ? (
        <video
          key={`${background?.sceneKey ?? "none"}:video`}
          className={styles.sceneVideo}
          src={sceneVideoUrl}
          poster={sceneImageUrl ?? undefined}
          autoPlay
          loop
          muted
          playsInline
          preload="auto"
          onError={() => setUnavailableVideoUrl(background?.videoUrl ?? null)}
        />
      ) : null}
    </div>
  );
}

function readMainScreenScene(): {
  experienceMode: ExperienceMode;
  config: AvatarDisplayConfig;
} {
  try {
    return {
      experienceMode: parseExperienceMode(window.localStorage.getItem(EXPERIENCE_MODE_STORAGE_KEY)),
      config: parseAvatarDisplayConfig(JSON.parse(
        window.localStorage.getItem(AVATAR_DISPLAY_CONFIG_STORAGE_KEY) ?? "null",
      )),
    };
  } catch {
    return {
      experienceMode: "voice",
      config: DEFAULT_AVATAR_DISPLAY_CONFIG,
    };
  }
}

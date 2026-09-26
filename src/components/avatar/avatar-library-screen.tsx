"use client";

import { useEffect, useState } from "react";
import type { AvatarAsset } from "@/lib/avatar-catalog";
import { loadCurrentAvatarCatalog, loadInternalPresetAvatars } from "@/lib/avatar-library-catalog-client";
import { INTERNAL_AVATAR_PRESET_IDS } from "@/lib/internal-avatar-presets";
import {
  AvatarAssetLibrary,
  type AvatarLibraryScope,
  type RealtimeAvatarScope,
} from "./avatar-asset-library";

export function AvatarLibraryScreen({
  initialScope = "realtime",
  initialRealtimeScope = "custom",
  embedded = false,
  returnTo,
}: {
  initialScope?: AvatarLibraryScope;
  initialRealtimeScope?: RealtimeAvatarScope;
  embedded?: boolean;
  returnTo?: string;
}) {
  const [avatars, setAvatars] = useState<AvatarAsset[] | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const fastInternalLoad = initialScope === "internal-preset";
    void loadCurrentAvatarCatalog(controller.signal, {
      includeHostedAvatars: !fastInternalLoad,
      includeOwnedBuiltinActions: true,
    })
      .then(setAvatars)
      .then(() => fastInternalLoad
        ? loadCurrentAvatarCatalog(controller.signal, { includeOwnedBuiltinActions: true }).then(setAvatars)
        : undefined)
      .catch((error) => {
        if (error instanceof Error && error.name === "AbortError") return;
        setAvatars(loadInternalPresetAvatars());
      });
    return () => {
      controller.abort();
    };
  }, [initialScope]);

  return (
    <AvatarAssetLibrary
      avatars={avatars ?? []}
      internalPresetIds={INTERNAL_AVATAR_PRESET_IDS}
      initialScope={initialScope}
      initialRealtimeScope={initialRealtimeScope}
      embedded={embedded}
      returnTo={returnTo}
      loading={avatars === null}
    />
  );
}

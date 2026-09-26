"use client";

import { useEffect, useState } from "react";
import type { AnamHostedAvatar } from "@/lib/anam-avatars";

export function officialRealtimeAvatarsFromCatalog(catalog: { configured?: boolean; avatars?: AnamHostedAvatar[] } | null): AnamHostedAvatar[] {
  return catalog?.configured && Array.isArray(catalog.avatars)
    ? catalog.avatars.filter((avatar) => avatar.origin === "official") : [];
}

export function personalRealtimeAvatarsFromCatalog(catalog: { configured?: boolean; avatars?: AnamHostedAvatar[] } | null): AnamHostedAvatar[] {
  return catalog?.configured && Array.isArray(catalog.avatars)
    ? catalog.avatars.filter((avatar) => avatar.origin === "personal") : [];
}

export function useOfficialRealtimeAvatars(enabled = true, revision = 0) {
  const [avatars, setAvatars] = useState<AnamHostedAvatar[]>([]);
  const [personalAvatars, setPersonalAvatars] = useState<AnamHostedAvatar[]>([]);
  const [configured, setConfigured] = useState(false);
  const [loading, setLoading] = useState(enabled);

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    void fetch("/api/anam/avatars", { cache: "no-store", signal: controller.signal })
      .then(async (response) => response.ok ? await response.json() as { configured?: boolean; avatars?: AnamHostedAvatar[] } : null)
      .then((catalog) => {
        if (!controller.signal.aborted) {
          setConfigured(Boolean(catalog?.configured));
          setAvatars(officialRealtimeAvatarsFromCatalog(catalog));
          setPersonalAvatars(personalRealtimeAvatarsFromCatalog(catalog));
        }
      })
      .catch(() => { if (!controller.signal.aborted) { setConfigured(false); setAvatars([]); setPersonalAvatars([]); } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [enabled, revision]);

  return { avatars, personalAvatars, configured, loading };
}

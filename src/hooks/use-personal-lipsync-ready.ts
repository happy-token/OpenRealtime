"use client";

import { useEffect, useState } from "react";

export function usePersonalLipsyncReady(enabled = true) {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    void fetch("/api/user/lipsync-service", { cache: "no-store", signal: controller.signal })
      .then(async (response) => response.ok ? response.json() as Promise<{ configured?: boolean }> : null)
      .then(async (data) => {
        if (!data?.configured || controller.signal.aborted) return;
        const response = await fetch("/api/user/lipsync-service", { method: "POST", signal: controller.signal });
        const status = await response.json() as { ready?: boolean };
        if (!controller.signal.aborted) setReady(response.ok && status.ready === true);
      }).catch(() => { if (!controller.signal.aborted) setReady(false); });
    return () => controller.abort();
  }, [enabled]);
  return ready;
}

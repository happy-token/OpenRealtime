"use client";

import { useCallback, useEffect, useState } from "react";
import type { AvatarCapabilities } from "@/lib/avatar-capabilities";

export function useAvatarCapabilities() {
  const [capabilities, setCapabilities] = useState<AvatarCapabilities | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => setAttempt((value) => value + 1), []);
  useEffect(() => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => {
      setError("能力检查超时，请重试。");
      controller.abort();
    }, 8_000);
    setCapabilities(null);
    setError(null);
    void fetch("/api/avatar-capabilities", { cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("能力信息暂时不可用，请重试。");
        const data = await response.json() as AvatarCapabilities;
        if (!["assets", "anam", "heygen", "localRenderer"].every((key) => {
          const value = data?.[key as keyof AvatarCapabilities];
          return value && ["available", "login_required", "not_configured"].includes(value.state)
            && typeof value.message === "string";
        })) throw new Error("能力信息暂时不可用，请重试。");
        if (!controller.signal.aborted) setCapabilities(data);
      }).catch(() => {
        if (!controller.signal.aborted) setError("能力信息暂时不可用，请重试。");
      }).finally(() => window.clearTimeout(timeout));
    return () => { window.clearTimeout(timeout); controller.abort(); };
  }, [attempt]);
  return { capabilities, error, retry };
}

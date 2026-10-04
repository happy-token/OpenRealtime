"use client";

import { useEffect, useState } from "react";

export type AdminState =
  | { status: "loading" }
  | { status: "signed-in"; username: string }
  | { status: "signed-out" }
  | { status: "unavailable" };

export function useCurrentAdmin(enabled = true): AdminState {
  const [state, setState] = useState<AdminState>({ status: "loading" });

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    void fetch("/api/admin/me", { cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        if (controller.signal.aborted) return;
        if (response.status === 401) {
          setState({ status: "signed-out" });
          return;
        }
        if (!response.ok) throw new Error("管理员状态读取失败");
        const payload = await response.json() as { username?: string };
        setState(payload.username
          ? { status: "signed-in", username: payload.username }
          : { status: "signed-out" });
      })
      .catch(() => { if (!controller.signal.aborted) setState({ status: "unavailable" }); });
    return () => controller.abort();
  }, [enabled]);

  return state;
}

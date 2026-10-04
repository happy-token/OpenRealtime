"use client";

import { useEffect, useState } from "react";

export type AppAdminState =
  | { status: "loading" }
  | { status: "admin" }
  | { status: "not-admin" }
  | { status: "unavailable" };

export function useCurrentAppAdmin(enabled = true): AppAdminState {
  const [state, setState] = useState<AppAdminState>({ status: "loading" });

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    void fetch("/api/user/is-admin", { cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        if (controller.signal.aborted) return;
        if (!response.ok) throw new Error("管理员状态读取失败");
        const payload = await response.json() as { isAdmin?: boolean };
        setState({ status: payload.isAdmin ? "admin" : "not-admin" });
      })
      .catch(() => { if (!controller.signal.aborted) setState({ status: "unavailable" }); });
    return () => controller.abort();
  }, [enabled]);

  return state;
}

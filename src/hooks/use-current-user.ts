"use client";

import { useEffect, useState } from "react";

export interface CurrentUser {
  issuer: string;
  subject: string;
}

export type CurrentUserState =
  | { status: "loading" }
  | { status: "signed-out" }
  | { status: "signed-in"; user: CurrentUser }
  | { status: "unavailable" };

export function accountLoginHref(nextPath: string): string {
  const safeNext = nextPath.startsWith("/") && !nextPath.startsWith("//") ? nextPath : "/settings/profile";
  return `/api/user/login?next=${encodeURIComponent(safeNext)}`;
}

export function accountIssuerLabel(issuer: string): string {
  try { return new URL(issuer).hostname; }
  catch { return issuer; }
}

export async function logoutCurrentUser(): Promise<void> {
  const response = await fetch("/api/user/logout", { method: "POST" });
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { error?: string } | null;
    throw new Error(payload?.error || "退出登录失败");
  }
}

export function useCurrentUser(): CurrentUserState {
  const [state, setState] = useState<CurrentUserState>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    void fetch("/api/user/me", { cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("账户状态读取失败");
        const payload = await response.json() as { signedIn?: boolean; user?: CurrentUser };
        if (controller.signal.aborted) return;
        setState(payload.signedIn && payload.user
          ? { status: "signed-in", user: payload.user }
          : { status: "signed-out" });
      })
      .catch(() => { if (!controller.signal.aborted) setState({ status: "unavailable" }); });
    return () => controller.abort();
  }, []);

  return state;
}

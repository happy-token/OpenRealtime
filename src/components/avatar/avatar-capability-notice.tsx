"use client";

import { CircleAlert, RefreshCw } from "lucide-react";
import Link from "next/link";
import type { AvatarCapability } from "@/lib/avatar-capabilities";

export function AvatarCapabilityNotice({ capability, error, onRetry, variant = "default" }: {
  capability?: AvatarCapability;
  error: string | null;
  onRetry: () => void;
  variant?: "default" | "stage";
}) {
  // The capability request normally resolves quickly after hydration. Keep that
  // transient state visually quiet so refreshing the homepage does not flash a
  // status card over the avatar; actionable results still remain visible.
  if (!error && (!capability || capability.state === "available")) return null;

  return <div
    className={`avatar-capability-notice${variant === "stage" ? " avatar-capability-notice--stage" : ""}`}
    data-tone={error ? "error" : "warning"}
    role="status"
  >
    {variant === "stage" ? <CircleAlert className="avatar-capability-notice__icon" aria-hidden="true" /> : null}
    <span className="avatar-capability-notice__message">{error ?? capability?.message}</span>
    {capability?.state === "login_required" && <Link href="/admin">管理员登录</Link>}
    {error && <button type="button" aria-label="重新检查" title="重新检查" onClick={onRetry}>
      {variant === "stage" ? <RefreshCw aria-hidden="true" /> : null}
      <span className={variant === "stage" ? "sr-only" : undefined}>重新检查</span>
    </button>}
  </div>;
}

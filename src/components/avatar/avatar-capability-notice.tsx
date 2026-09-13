"use client";

import Link from "next/link";
import type { AvatarCapability } from "@/lib/avatar-capabilities";

export function AvatarCapabilityNotice({ capability, error, onRetry }: {
  capability?: AvatarCapability;
  error: string | null;
  onRetry: () => void;
}) {
  // The capability request normally resolves quickly after hydration. Keep that
  // transient state visually quiet so refreshing the homepage does not flash a
  // status card over the avatar; actionable results still remain visible.
  if (!error && (!capability || capability.state === "available")) return null;

  return <div className="avatar-capability-notice" role="status">
    <span>{error ?? capability?.message}</span>
    {capability?.state === "login_required" && <Link href="/admin">管理员登录</Link>}
    {error && <button type="button" onClick={onRetry}>重新检查</button>}
  </div>;
}

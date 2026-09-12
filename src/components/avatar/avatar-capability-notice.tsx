"use client";

import Link from "next/link";
import type { AvatarCapability } from "@/lib/avatar-capabilities";

export function AvatarCapabilityNotice({ capability, error, onRetry }: {
  capability?: AvatarCapability;
  error: string | null;
  onRetry: () => void;
}) {
  if (!error && capability?.state === "available") return null;

  return <div className="avatar-capability-notice" role="status">
    <span>{error ?? capability?.message ?? "正在检查数字人能力…"}</span>
    {capability?.state === "login_required" && <Link href="/admin">管理员登录</Link>}
    {error && <button type="button" onClick={onRetry}>重新检查</button>}
  </div>;
}

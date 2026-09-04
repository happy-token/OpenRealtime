import type { Metadata } from "next";
import { AvatarDetailScreen } from "@/components/avatar/avatar-detail-screen";
import { AvatarPageShell } from "@/components/avatar/avatar-page-shell";

export const metadata: Metadata = { title: "Avatar 详情 — OpenRealtime" };

export default async function AvatarDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ avatarId: string }>;
  searchParams: Promise<{ return_scope?: string; return_realtime_scope?: string }>;
}) {
  const { avatarId } = await params;
  const returnQuery = await searchParams;
  const backHref = avatarLibraryReturnHref(returnQuery.return_scope, returnQuery.return_realtime_scope);
  return (
    <AvatarPageShell
      active="library"
      back={{ href: backHref, label: "返回资产管理" }}
    >
      <AvatarDetailScreen avatarId={avatarId} backHref={backHref} />
    </AvatarPageShell>
  );
}

function avatarLibraryReturnHref(scope?: string, realtimeScope?: string) {
  if (scope === "internal-preset") return "/avatars?scope=internal-preset";
  if (scope === "realtime" && realtimeScope === "built-in") {
    return "/avatars?scope=realtime&realtime_scope=built-in";
  }
  if (scope === "realtime") return "/avatars?scope=realtime&realtime_scope=custom";
  return "/avatars";
}

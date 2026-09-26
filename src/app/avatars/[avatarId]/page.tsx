import type { Metadata } from "next";
import { AvatarDetailScreen } from "@/components/avatar/avatar-detail-screen";
import { AvatarPageShell } from "@/components/avatar/avatar-page-shell";
import { isRoleRecordId } from "@/lib/role-records";

export const metadata: Metadata = { title: "Avatar 详情 — OpenRealtime" };

export default async function AvatarDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ avatarId: string }>;
  searchParams: Promise<{ return_scope?: string; return_realtime_scope?: string; avatar_action_id?: string; return_to?: string }>;
}) {
  const { avatarId } = await params;
  const returnQuery = await searchParams;
  const returnToRoleCreate = returnQuery.return_to === "role-create";
  const returnToRoleId = isRoleRecordId(returnQuery.return_to)
    ? returnQuery.return_to
    : undefined;
  const backHref = returnToRoleCreate
    ? "/roles/new"
    : returnToRoleId
    ? `/roles/${encodeURIComponent(returnToRoleId)}`
    : avatarLibraryReturnHref(returnQuery.return_scope, returnQuery.return_realtime_scope);
  return (
    <AvatarPageShell
      active="library"
      back={{ href: backHref, label: returnToRoleCreate ? "返回创建角色" : returnToRoleId ? "返回当前角色" : "返回资产管理" }}
    >
      <AvatarDetailScreen avatarId={avatarId} backHref={backHref} initialActionId={returnQuery.avatar_action_id} returnTo={returnToRoleCreate ? "role-create" : returnToRoleId} />
    </AvatarPageShell>
  );
}

function avatarLibraryReturnHref(scope?: string, realtimeScope?: string) {
  if (scope === "internal-preset") return "/resources?tab=avatars&scope=internal-preset";
  if (scope === "realtime" && realtimeScope === "built-in") {
    return "/resources?tab=avatars&scope=realtime&realtime_scope=built-in";
  }
  if (scope === "realtime") return "/resources?tab=avatars&scope=realtime&realtime_scope=custom";
  return "/resources?tab=avatars";
}

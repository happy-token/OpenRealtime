import type { Metadata } from "next";
import { AvatarPageShell } from "@/components/avatar/avatar-page-shell";
import { AvatarTrashScreen } from "@/components/avatar/avatar-trash-screen";
import { isRoleRecordId } from "@/lib/role-records";

export const metadata: Metadata = { title: "Avatar 回收站 — OpenRealtime" };

export default async function AvatarTrashPage({ searchParams }: { searchParams: Promise<{ return_to?: string }> }) {
  const query = await searchParams;
  const back = query.return_to === "role-create"
    ? { href: "/roles/new", label: "返回创建角色" }
    : isRoleRecordId(query.return_to)
      ? { href: `/roles/${encodeURIComponent(query.return_to)}`, label: "返回当前角色" }
      : { href: "/resources?tab=avatars", label: "返回数字人资源" };
  return <AvatarPageShell
    active="library"
    back={back}
  ><AvatarTrashScreen returnHref={back.href} /></AvatarPageShell>;
}

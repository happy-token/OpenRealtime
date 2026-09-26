import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { avatarResourceHref } from "@/lib/avatar-workbench-navigation";
import { isRoleRecordId } from "@/lib/role-records";

export const metadata: Metadata = { title: "动作生成 — OpenRealtime" };

export default async function MotionServicePage({ searchParams }: { searchParams: Promise<{ avatar_id?: string; return_to?: string }> }) {
  const query = await searchParams;
  const returnTo = query.return_to === "role-create" || isRoleRecordId(query.return_to) ? query.return_to : undefined;
  const avatarId = typeof query.avatar_id === "string" && /^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$/.test(query.avatar_id)
    ? query.avatar_id
    : undefined;
  redirect(avatarResourceHref({ task: "motion", avatarId, returnTo }));
}

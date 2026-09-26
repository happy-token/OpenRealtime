import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { avatarResourceHref } from "@/lib/avatar-workbench-navigation";
import { isRoleRecordId } from "@/lib/role-records";

export const metadata: Metadata = {
  title: "创建数字人 — OpenRealtime",
  description: "创建统一 Avatar 形象，并按需添加实时驱动和多个动作。",
};

export default async function CreateAvatarPage({
  searchParams,
}: {
  searchParams: Promise<{ task?: string; avatar_id?: string; avatar_action_id?: string; return_to?: string; method?: string }>;
}) {
  const query = await searchParams;
  const validAssetId = (value: string | undefined) => typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$/.test(value)
    ? value
    : undefined;
  const returnTo = query.return_to === "role-create" || isRoleRecordId(query.return_to) ? query.return_to : undefined;
  redirect(avatarResourceHref({
    task: query.task === "action" ? "motion" : "avatar",
    avatarId: validAssetId(query.avatar_id),
    actionId: validAssetId(query.avatar_action_id),
    returnTo,
    method: query.method === "lipforcing" ? "lipforcing" : undefined,
  }));
}

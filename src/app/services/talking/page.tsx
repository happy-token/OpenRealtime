import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { avatarResourceHref } from "@/lib/avatar-workbench-navigation";
import { isRoleRecordId } from "@/lib/role-records";

export const metadata: Metadata = { title: "口型对齐 — OpenRealtime" };

const ASSET_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$/;

export default async function TalkingServicePage({ searchParams }: { searchParams: Promise<{ avatar_id?: string; action_id?: string; return_to?: string; method?: string }> }) {
  const query = await searchParams;
  const returnTo = query.return_to === "role-create" || isRoleRecordId(query.return_to) ? query.return_to : undefined;
  const avatarId = typeof query.avatar_id === "string" && ASSET_ID.test(query.avatar_id) ? query.avatar_id : undefined;
  const actionId = typeof query.action_id === "string" && ASSET_ID.test(query.action_id) ? query.action_id : undefined;
  redirect(avatarResourceHref({
    task: "talking",
    avatarId,
    actionId,
    returnTo,
    method: query.method === "lipforcing" ? "lipforcing" : undefined,
  }));
}

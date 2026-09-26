import { redirect } from "next/navigation";
import { avatarResourceHref } from "@/lib/avatar-workbench-navigation";

export default async function RoleTalkingCreatePage({ params, searchParams }: {
  params: Promise<{ roleId: string }>;
  searchParams: Promise<{ avatar_id?: string; action_id?: string }>;
}) {
  const [{ roleId }, query] = await Promise.all([params, searchParams]);
  redirect(avatarResourceHref({
    task: "talking",
    avatarId: query.avatar_id,
    actionId: query.action_id,
    returnTo: roleId,
    method: "lipforcing",
  }));
}

import { redirect } from "next/navigation";
import { avatarResourceHref } from "@/lib/avatar-workbench-navigation";
import { isRoleRecordId } from "@/lib/role-records";

export default async function RoleActionPage({
  searchParams,
}: {
  searchParams: Promise<{ avatar_id?: string; return_to?: string }>;
}) {
  const query = await searchParams;
  redirect(avatarResourceHref({
    task: "motion",
    avatarId: query.avatar_id,
    returnTo: isRoleRecordId(query.return_to) ? query.return_to : undefined,
  }));
}

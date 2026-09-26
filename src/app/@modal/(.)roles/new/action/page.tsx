import { RoleActionComposer } from "@/components/roles/role-action-composer";

export default async function InterceptedRoleActionPage({
  searchParams,
}: {
  searchParams: Promise<{ avatar_id?: string }>;
}) {
  const query = await searchParams;
  return <RoleActionComposer avatarId={typeof query.avatar_id === "string" ? query.avatar_id : ""} presentation="window" />;
}

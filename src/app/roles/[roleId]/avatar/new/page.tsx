import { redirect } from "next/navigation";
import { avatarResourceHref } from "@/lib/avatar-workbench-navigation";

export default async function RoleAvatarCreatePage({ params }: { params: Promise<{ roleId: string }> }) {
  const { roleId } = await params;
  redirect(avatarResourceHref({ task: "avatar", returnTo: roleId }));
}

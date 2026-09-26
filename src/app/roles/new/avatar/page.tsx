import { redirect } from "next/navigation";
import { avatarResourceHref } from "@/lib/avatar-workbench-navigation";

export default function RoleAvatarPage() {
  redirect(avatarResourceHref({ task: "avatar" }));
}

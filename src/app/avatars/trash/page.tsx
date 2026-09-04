import type { Metadata } from "next";
import { AvatarPageShell } from "@/components/avatar/avatar-page-shell";
import { AvatarTrashScreen } from "@/components/avatar/avatar-trash-screen";

export const metadata: Metadata = { title: "Avatar 回收站 — OpenRealtime" };

export default function AvatarTrashPage() {
  return <AvatarPageShell active="library"><AvatarTrashScreen /></AvatarPageShell>;
}

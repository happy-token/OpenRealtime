import type { Metadata } from "next";
import { AvatarPageShell } from "@/components/avatar/avatar-page-shell";
import { AvatarStudio } from "@/components/avatar/avatar-studio";

export const metadata: Metadata = {
  title: "创建数字人 — OpenRealtime",
  description: "创建统一 Avatar 形象，并按需添加实时驱动和多个动作。",
};

export default async function CreateAvatarPage({
  searchParams,
}: {
  searchParams: Promise<{ task?: string; avatar_id?: string }>;
}) {
  const query = await searchParams;
  return (
    <AvatarPageShell active="create" pageTitle="创建数字人">
      <AvatarStudio
        initialTask={query.task === "lightweight" ? "lightweight" : query.task === "action" ? "action" : "realtime"}
        initialAvatarId={typeof query.avatar_id === "string" ? query.avatar_id : ""}
      />
    </AvatarPageShell>
  );
}

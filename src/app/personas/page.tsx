import type { Metadata } from "next";
import { AvatarPageShell } from "@/components/avatar/avatar-page-shell";
import { PersonaLibraryScreen } from "@/components/persona/persona-library-screen";

export const metadata: Metadata = {
  title: "Persona 库 — OpenRealtime",
  description: "关联现有 Persona 或创建新的 Persona，管理数字人的人格配置文件。",
};

export default async function PersonasPage({
  searchParams,
}: {
  searchParams: Promise<{ avatar_id?: string; avatar_display_name?: string }>;
}) {
  const query = await searchParams;
  const linkingAvatarId = typeof query.avatar_id === "string" && query.avatar_id ? query.avatar_id : undefined;
  const linkingAvatarDisplayName = typeof query.avatar_display_name === "string" ? query.avatar_display_name : "";

  return (
    <AvatarPageShell active="personas" pageTitle="Persona 库">
      <PersonaLibraryScreen linkingAvatarId={linkingAvatarId} linkingAvatarDisplayName={linkingAvatarDisplayName} />
    </AvatarPageShell>
  );
}

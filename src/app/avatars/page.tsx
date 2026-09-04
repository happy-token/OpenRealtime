import type { Metadata } from "next";
import { AvatarLibraryScreen } from "@/components/avatar/avatar-library-screen";
import { AvatarPageShell } from "@/components/avatar/avatar-page-shell";
import type { AvatarLibraryScope, RealtimeAvatarScope } from "@/components/avatar/avatar-asset-library";

export const metadata: Metadata = {
  title: "数字人资产 — OpenRealtime",
  description: "管理 Avatar 形象、实时驱动绑定、动作与模型准备状态。",
};

export default async function AvatarLibraryPage({
  searchParams,
}: {
  searchParams: Promise<{ scope?: string; realtime_scope?: string }>;
}) {
  const query = await searchParams;
  const initialScope: AvatarLibraryScope = query.scope === "internal-preset" ? "internal-preset" : "realtime";
  const initialRealtimeScope: RealtimeAvatarScope = query.realtime_scope === "built-in" ? "built-in" : "custom";

  return (
    <AvatarPageShell active="library" pageTitle="数字人资产">
      <AvatarLibraryScreen initialScope={initialScope} initialRealtimeScope={initialRealtimeScope} />
    </AvatarPageShell>
  );
}

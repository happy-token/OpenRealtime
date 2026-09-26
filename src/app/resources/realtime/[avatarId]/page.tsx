import { RealtimeAvatarSettings } from "@/components/workspace/realtime-avatar-settings";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";

export default async function RealtimeAvatarSettingsPage({ params }: { params: Promise<{ avatarId: string }> }) {
  const { avatarId } = await params;
  return <WorkspaceShell resourceTab="official-realtime" immersive><RealtimeAvatarSettings avatarId={avatarId} /></WorkspaceShell>;
}

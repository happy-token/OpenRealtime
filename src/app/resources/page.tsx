import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { ResourceLibraryScreen, type ResourceTab } from "@/components/workspace/resource-library-screen";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";
import { isRoleRecordId } from "@/lib/role-records";
import type { AvatarWorkbenchTask } from "@/lib/avatar-workbench-navigation";

export const metadata: Metadata = { title: "资源库 — OpenRealtime" };

const RESOURCE_TABS = new Set<ResourceTab>(["voices", "personas", "tools", "knowledge", "avatars", "official-realtime"]);
const AVATAR_TASKS = new Set<AvatarWorkbenchTask>(["avatar", "motion", "talking", "realtime"]);

export default async function ResourcesPage({ searchParams }: {
  searchParams: Promise<{ tab?: string; scope?: string; realtime_scope?: string; return_to?: string; task?: string; avatar_id?: string; action_id?: string; method?: string }>;
}) {
  const query = await searchParams;
  const requested = query.tab as ResourceTab | undefined;
  const tab = requested && RESOURCE_TABS.has(requested) ? requested : "voices";
  const returnTo = query.return_to === "role-create" || isRoleRecordId(query.return_to) ? query.return_to : undefined;
  if (query.tab === "motion") {
    const params = new URLSearchParams({ tab: "avatars", task: "motion" });
    if (returnTo) params.set("return_to", returnTo);
    redirect(`/resources?${params.toString()}`);
  }
  const avatarTask = AVATAR_TASKS.has(query.task as AvatarWorkbenchTask) ? query.task as AvatarWorkbenchTask : undefined;
  return <WorkspaceShell resourceTab={tab} resourceReturnTo={returnTo} immersive={tab === "avatars"}><ResourceLibraryScreen
    tab={tab}
    avatarTask={avatarTask}
    initialAvatarId={query.avatar_id}
    initialActionId={query.action_id}
    initialTalkingMethod={query.method === "lipforcing" ? "lipforcing" : undefined}
    returnToRoleCreate={returnTo === "role-create"}
    returnToRoleId={isRoleRecordId(returnTo) ? returnTo : undefined}
  /></WorkspaceShell>;
}

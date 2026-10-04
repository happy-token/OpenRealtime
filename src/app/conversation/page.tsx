import type { Metadata } from "next";
import { headers } from "next/headers";
import { OpenRealtimeApp } from "@/components/open-realtime-app";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";
import { currentAdmin } from "@/lib/admin-server";
import { avatarEvaluationPreviewPolicyFromEnv } from "@/lib/avatar-evaluation-preview";
import { findRole } from "@/lib/role-catalog-repository";
import { findPersonalRole } from "@/lib/personal-role-library";
import { userFromRequest } from "@/lib/user-session";
import { readUserDefaultRole } from "@/lib/user-default-role";
import { LOCAL_DEFAULT_ROLE_OWNER, localDefaultRoleOwnerForPage } from "@/lib/default-role-owner";
import { isRolePresentationMode } from "@/lib/role-records";
import { listTools } from "@/lib/tool-catalog-repository";
import { notFound } from "next/navigation";
import { conversationOwner } from "@/lib/conversation-history-auth";
import { getConversation } from "@/lib/conversation-history";
import { avatarIdFromHostedRoleId } from "@/lib/hosted-avatar-role-id";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "对话 — OpenRealtime" };

export default async function ConversationPage({ searchParams }: {
  searchParams: Promise<{ role_id?: string; role_mode?: string; official_avatar_id?: string; realtime_avatar_id?: string; continue?: string }>;
}) {
  const previewPolicy = avatarEvaluationPreviewPolicyFromEnv();
  const [admin, query, requestHeaders] = await Promise.all([currentAdmin(), searchParams, headers()]);
  const request = new Request("http://localhost/conversation", { headers: requestHeaders });
  const owner = query.continue ? await conversationOwner(request) : null;
  const initialConversation = query.continue && typeof owner === "string" ? await getConversation(owner, query.continue) : null;
  if (query.continue) {
    if (!initialConversation?.thread_id || !initialConversation.voice_session_id) notFound();
    // Select the saved role on the server; URL parameters cannot change its identity.
    const avatarId = initialConversation.role_id ? avatarIdFromHostedRoleId(initialConversation.role_id) : null;
    query.role_id = avatarId ? undefined : initialConversation.role_id ?? "default-assistant";
    query.role_mode = initialConversation.mode;
    query.realtime_avatar_id = avatarId ?? undefined;
    query.official_avatar_id = undefined;
  }
  const avatarArtifactPreviewEnabled = previewPolicy.enabled
    && (previewPolicy.localDevelopmentAccess || Boolean(admin));
  const hostedAvatarId = query.realtime_avatar_id ?? query.official_avatar_id;
  const user = await userFromRequest(new Request("http://localhost", { headers: requestHeaders }));
  const defaultOwner = user ?? (admin ? LOCAL_DEFAULT_ROLE_OWNER : localDefaultRoleOwnerForPage(requestHeaders.get("host")));
  const roleId = query.role_id ?? (hostedAvatarId ? "" : (defaultOwner ? await readUserDefaultRole(defaultOwner).catch(() => null) : null) ?? "default-assistant");
  const selectedRole = !roleId ? null : roleId.startsWith("role-personal-")
    ? user ? await findPersonalRole(user, roleId).catch(() => null) : null
    : await findRole(roleId).catch(() => null);
  const role = selectedRole ?? (query.role_id || hostedAvatarId ? null : await findRole("default-assistant").catch(() => null));
  if (initialConversation && !role && !hostedAvatarId) notFound();
  if (initialConversation && role && (!isRolePresentationMode(initialConversation.mode)
    || !role.enabled_modes.includes(initialConversation.mode))) notFound();
  const roleMode = isRolePresentationMode(query.role_mode) && role?.enabled_modes.includes(query.role_mode)
    ? query.role_mode
    : role?.default_mode;
  const initialToolNames = role?.tool_ids.length
    ? (await listTools()).filter((tool) => tool.enabled && role.tool_ids.includes(tool.tool_id) && (tool.builtin || Boolean(tool.endpoint))).map((tool) => tool.function_name)
    : [];
  return <WorkspaceShell session>
    <OpenRealtimeApp
      initialRole={role}
      initialConversation={initialConversation}
      initialRoleMode={roleMode}
      officialAvatarId={typeof hostedAvatarId === "string" && hostedAvatarId.length <= 120 ? hostedAvatarId : undefined}
      initialToolNames={initialToolNames}
      avatarArtifactPreviewEnabled={avatarArtifactPreviewEnabled}
      publicVoiceEnabled={process.env.VOICEAGENT_PUBLIC_VOICE_ENABLED === "true"
        && process.env.VOICEAGENT_ENDPOINT_AUTH_MODE === "public_ticket"}
      defaultTtsProvider={process.env.VOICEAGENT_TTS_BACKEND === "bailian" ? "bailian" : "doubao"}
    />
  </WorkspaceShell>;
}

import { OpenRealtimeApp } from "@/components/open-realtime-app";
import { currentAdmin } from "@/lib/admin-server";
import { avatarEvaluationPreviewPolicyFromEnv } from "@/lib/avatar-evaluation-preview";

export const dynamic = "force-dynamic";

export default async function Home() {
  const previewPolicy = avatarEvaluationPreviewPolicyFromEnv();
  const avatarArtifactPreviewEnabled = previewPolicy.enabled
    && (previewPolicy.localDevelopmentAccess || Boolean(await currentAdmin()));
  return <OpenRealtimeApp avatarArtifactPreviewEnabled={avatarArtifactPreviewEnabled} />;
}

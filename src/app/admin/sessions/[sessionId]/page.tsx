import { redirect } from "next/navigation";

export default async function SessionPage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = await params;
  redirect(`/settings/session-diagnostics/sessions/${encodeURIComponent(sessionId)}`);
}

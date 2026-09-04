import { redirect } from "next/navigation";
import { SessionDiagnostics } from "@/components/admin/session-diagnostics";
import { currentAdmin } from "@/lib/admin-server";

export const dynamic = "force-dynamic";

export default async function SessionPage({ params }: { params: Promise<{ sessionId: string }> }) {
  if (!await currentAdmin()) redirect("/admin");
  const { sessionId } = await params;
  if (!sessionId || sessionId.length > 128) redirect("/admin");
  return <SessionDiagnostics sessionId={sessionId} />;
}

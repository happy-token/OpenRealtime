import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { SessionDiagnostics } from "@/components/admin/session-diagnostics";
import { currentAppAdmin } from "@/lib/admin-server";

export const dynamic = "force-dynamic";

export default async function SessionPage({ params }: { params: Promise<{ sessionId: string }> }) {
  if (!await currentAppAdmin(new Request("http://localhost", { headers: await headers() }))) redirect("/settings/session-diagnostics");
  const { sessionId } = await params;
  if (!sessionId || sessionId.length > 128) redirect("/settings/session-diagnostics");
  return <SessionDiagnostics sessionId={sessionId} />;
}

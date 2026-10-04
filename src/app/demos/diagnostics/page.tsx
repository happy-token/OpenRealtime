import { notFound } from "next/navigation";
import { AdminDashboard } from "@/components/admin/admin-dashboard";
import { SessionDiagnostics } from "@/components/admin/session-diagnostics";
import { diagnosticsPreview } from "@/lib/diagnostics-preview";
export const dynamic = "force-dynamic";
export default async function DiagnosticsPreview({ searchParams }: { searchParams: Promise<{ session?: string }> }) {
  if (process.env.NODE_ENV === "production") notFound();
  const { session } = await searchParams;
  if (session) {
    const report = diagnosticsPreview.reports.find(item => item.session_id === session);
    if (!report) notFound();
    return <SessionDiagnostics sessionId={session} preview={report} />;
  }
  return <AdminDashboard username="主题预览" preview={diagnosticsPreview} />;
}

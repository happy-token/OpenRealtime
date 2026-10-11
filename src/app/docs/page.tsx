import { DocumentIndex } from "@/components/docs/document-pages";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";

export const metadata = { title: "文档 · OpenRealtime" };
export default function DocumentsPage() {
  return <WorkspaceShell><DocumentIndex /></WorkspaceShell>;
}

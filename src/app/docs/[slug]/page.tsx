import { notFound } from "next/navigation";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { DocumentReader } from "@/components/docs/document-pages";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";
import { PUBLIC_DOCUMENTS } from "@/lib/public-documents";

export default async function DocumentPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const doc = PUBLIC_DOCUMENTS.find(item => item.slug === slug);
  if (!doc) notFound();
  const markdown = await readFile(path.join(process.cwd(), "docs", doc.file), "utf8");
  const heading = markdown.match(/^#\s+([^\r\n]+)\r?\n/);
  const title = heading?.[1] ?? doc.title;
  const content = heading ? markdown.slice(heading[0].length).trimStart() : markdown;
  return <WorkspaceShell><DocumentReader slug={slug} title={title} content={content} /></WorkspaceShell>;
}


import { LocalizedText } from "@/components/language/language-provider";
import Link from "next/link";
import { BookOpen, ChevronDown } from "lucide-react";
import { notFound } from "next/navigation";
import { readFile } from "node:fs/promises";
import path from "node:path";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";
import { PUBLIC_DOCUMENTS } from "@/lib/public-documents";
import styles from "../docs.module.css";
export default async function DocumentPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const doc = PUBLIC_DOCUMENTS.find(item => item.slug === slug);
  if (!doc) notFound();
  const markdown = await readFile(path.join(process.cwd(), "docs", doc.file), "utf8");
  const heading = markdown.match(/^#\s+([^\r\n]+)\r?\n/);
  const title = heading?.[1] ?? doc.title;
  const content = heading ? markdown.slice(heading[0].length).trimStart() : markdown;
  return <WorkspaceShell><div className={`${styles.page} ${styles.reader}`} tabIndex={0} aria-label="文档阅读区域">
    <header className={styles.documentHeader}>
      <div><h1>{title}</h1><p>{doc.category}</p></div>
      <details className={styles.documentMenu}>
        <summary><BookOpen aria-hidden="true" /><span>{<LocalizedText text={"文档目录"} />}</span><ChevronDown aria-hidden="true" /></summary>
        <nav aria-label="文档目录">
          <Link href="/docs" aria-label="全部文档">{<LocalizedText text={"全部文档"} />}</Link>
          {PUBLIC_DOCUMENTS.map(item => <Link key={item.slug} href={`/docs/${item.slug}`} aria-label={item.title} aria-current={item.slug === slug ? "page" : undefined}><small>{item.category}</small><span>{item.title}</span></Link>)}
        </nav>
      </details>
    </header>
    <article className={styles.article}><ReactMarkdown remarkPlugins={[remarkGfm]} components={{ table: ({ children }) => <div className={styles.table}><table>{children}</table></div> }}>{content}</ReactMarkdown></article>
  </div></WorkspaceShell>;
}

import Link from "next/link";
import { notFound } from "next/navigation";
import { readFile } from "node:fs/promises";
import path from "node:path";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { PUBLIC_DOCUMENTS } from "@/lib/public-documents";
import styles from "../docs.module.css";
export default async function DocumentPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const doc = PUBLIC_DOCUMENTS.find(item => item.slug === slug);
  if (!doc) notFound();
  const markdown = await readFile(path.join(process.cwd(), "docs", doc.file), "utf8");
  return <main className={styles.page} tabIndex={0} aria-label="文档阅读区域"><nav><Link href="/docs">← 文档</Link><Link href="/">返回首页</Link></nav><article className={styles.article}><ReactMarkdown remarkPlugins={[remarkGfm]} components={{ table: ({ children }) => <div className={styles.table}><table>{children}</table></div> }}>{markdown}</ReactMarkdown></article></main>;
}

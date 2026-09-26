import Link from "next/link";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";
import { PUBLIC_DOCUMENTS } from "@/lib/public-documents";
import styles from "./docs.module.css";
export const metadata = { title: "文档 · OpenRealtime" };
export default function DocumentsPage() {
  return <WorkspaceShell><div className={styles.page} tabIndex={0} aria-label="文档阅读区域"><header className={styles.indexHeader}><h1>文档</h1><p>技术文章与使用说明</p></header><div className={styles.list}>{PUBLIC_DOCUMENTS.map(doc => <Link key={doc.slug} href={`/docs/${doc.slug}`} className={styles.card}><small>{doc.category}</small><h2>{doc.title}</h2><p>{doc.description}</p></Link>)}</div></div></WorkspaceShell>;
}

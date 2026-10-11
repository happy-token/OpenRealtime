"use client";

import Link from "next/link";
import { BookOpen, ChevronDown } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useLanguage } from "@/components/language/language-provider";
import { PUBLIC_DOCUMENTS } from "@/lib/public-documents";
import styles from "@/app/docs/docs.module.css";

export function DocumentIndex() {
  const { t } = useLanguage();
  return <div className={styles.page} tabIndex={0} aria-label={t("文档阅读区域")}>
    <header className={styles.indexHeader}><h1>{t("文档")}</h1><p>{t("技术文章与使用说明")}</p></header>
    <div className={styles.list}>{PUBLIC_DOCUMENTS.map(doc => <Link key={doc.slug} href={`/docs/${doc.slug}`} className={styles.card}>
      <small>{t(doc.category)}</small><h2>{t(doc.title)}</h2><p>{t(doc.description)}</p>
    </Link>)}</div>
  </div>;
}

export function DocumentReader({ slug, title, content }: { slug: string; title: string; content: string }) {
  const { t, language } = useLanguage();
  const doc = PUBLIC_DOCUMENTS.find(item => item.slug === slug)!;
  return <div className={`${styles.page} ${styles.reader}`} tabIndex={0} aria-label={t("文档阅读区域")}>
    <header className={styles.documentHeader}>
      <div><h1>{language === "en" ? t(doc.title) : title}</h1><p>{t(doc.category)}</p></div>
      <details className={styles.documentMenu}>
        <summary><BookOpen aria-hidden="true" /><span>{t("文档目录")}</span><ChevronDown aria-hidden="true" /></summary>
        <nav aria-label={t("文档目录")}>
          <Link href="/docs" aria-label={t("全部文档")}>{t("全部文档")}</Link>
          {PUBLIC_DOCUMENTS.map(item => <Link key={item.slug} href={`/docs/${item.slug}`} aria-label={t(item.title)} aria-current={item.slug === slug ? "page" : undefined}><small>{t(item.category)}</small><span>{t(item.title)}</span></Link>)}
        </nav>
      </details>
    </header>
    <article className={styles.article} lang="zh-CN"><ReactMarkdown remarkPlugins={[remarkGfm]} components={{ table: ({ children }) => <div className={styles.table}><table>{children}</table></div> }}>{content}</ReactMarkdown></article>
  </div>;
}

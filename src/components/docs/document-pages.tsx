"use client";

import Link from "next/link";
import { BookOpen, ChevronDown } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useLanguage } from "@/components/language/language-provider";
import { DOCUMENT_SECTIONS, PUBLIC_DOCUMENTS, resolveDocumentLink, type PublicDocument } from "@/lib/public-documents";
import { remarkDocumentHeadings } from "@/lib/document-markdown";
import styles from "@/app/docs/docs.module.css";

export function DocumentIndex() {
  const { t } = useLanguage();
  const highlights = [
    { title: "自由组合，打造你的语音 Agent", description: "灵活选择 TTS、LLM、声音与人设，定制助手的表达方式与能力。" },
    { title: "智能判停，给思考留时间", description: "结合语义与说话状态判断是否说完，让助手在合适的时机接话。" },
    { title: "智能打断，听懂你的意图", description: "区分打断与附和，减少噪声误触发；叫停或纠正时及时响应。" },
  ];
  const cards = (docs: readonly PublicDocument[]) => <div className={styles.list}>{docs.map(doc => <Link key={doc.slug} href={`/docs/${doc.slug}`} className={styles.card}>
    <small>{doc.englishFile ? t("中英双语") : doc.language === "en" ? "English" : t("中文")}</small>
    <h3>{t(doc.title)}</h3><p>{t(doc.description)}</p>
  </Link>)}</div>;
  return <div className={`${styles.page} ${styles.index}`} tabIndex={0} aria-label={t("文档阅读区域")}>
    <header className={styles.indexHeader}>
      <span className={styles.eyebrow}>{t("OpenRealtime 文档")}</span>
      <h1>{t("用语音聊天和工作")}</h1>
      <p>{t("一个开源、可自定义、可打断的实时语音交互 Agent。接入你的 Agent，自然交流、查询资料，并通过已配置的工具辅助工作。")}</p>
      <p>{t("按预算选择语音与模型服务，配置自己的声音、人设和能力。数字人按需添加。")}</p>
      <div className={styles.entryLinks}>
        <Link className={styles.primaryLink} href="/conversation?role_mode=conversation&experience=voice">{t("体验实时语音")}</Link>
        <Link href="/docs/quick-start">{t("快速指南")}</Link>
        <Link href="/docs/role-configuration">{t("定制语音 Agent")}</Link>
        <Link href="/docs/chat-agent-integration">{t("接入你的 Agent")} →</Link>
      </div>
    </header>
    <section className={styles.highlights} aria-label={t("核心亮点")}>
      {highlights.map(highlight => <div key={highlight.title}>
        <h2>{t(highlight.title)}</h2><p>{t(highlight.description)}</p>
      </div>)}
    </section>
    {DOCUMENT_SECTIONS.map((section, index) => {
      const docs = PUBLIC_DOCUMENTS.filter(doc => doc.category === section.title);
      const headingId = `document-section-${index}`;
      if (section.title === "研究与规划") return <details key={section.title} className={styles.research}>
        <summary>{t(section.title)}</summary><p>{t(section.description)}</p>{cards(docs)}
      </details>;
      return <section key={section.title} className={styles.section} aria-labelledby={headingId}>
        <h2 id={headingId}>{t(section.title)}</h2><p className={styles.sectionDescription}>{t(section.description)}</p>{cards(docs)}
      </section>;
    })}
  </div>;
}

export function DocumentReader({ slug, title, content, englishContent }: { slug: string; title: string; content: string; englishContent?: string }) {
  const { t, language } = useLanguage();
  const doc = PUBLIC_DOCUMENTS.find(item => item.slug === slug)!;
  const useEnglish = language === "en" && doc.englishFile !== undefined && englishContent !== undefined;
  const articleLanguage = useEnglish ? "en" : doc.language ?? "zh-CN";
  const sourceFile = useEnglish ? doc.englishFile! : doc.file;
  return <div className={`${styles.page} ${styles.reader}`} tabIndex={0} aria-label={t("文档阅读区域")}>
    <header className={styles.documentHeader}>
      <div><h1>{language === "en" ? t(doc.title) : title}</h1><p>{t(doc.category)} · {t("正文语言")}: {articleLanguage === "en" ? "English" : t("中文")}</p></div>
      <details className={styles.documentMenu}>
        <summary><BookOpen aria-hidden="true" /><span>{t("文档目录")}</span><ChevronDown aria-hidden="true" /></summary>
        <nav aria-label={t("文档目录")}>
          <Link href="/docs" aria-label={t("全部文档")}>{t("全部文档")}</Link>
          {PUBLIC_DOCUMENTS.map(item => <Link key={item.slug} href={`/docs/${item.slug}`} aria-label={t(item.title)} aria-current={item.slug === slug ? "page" : undefined}><small>{t(item.category)}</small><span>{t(item.title)}</span></Link>)}
        </nav>
      </details>
    </header>
    <article className={styles.article} lang={articleLanguage}><ReactMarkdown remarkPlugins={[remarkGfm, remarkDocumentHeadings]} components={{
      a: ({ href, children }) => <a href={href ? resolveDocumentLink(href, sourceFile) : undefined}>{children}</a>,
      table: ({ children }) => <div className={styles.table}><table>{children}</table></div>,
    }}>{useEnglish ? englishContent : content}</ReactMarkdown></article>
  </div>;
}

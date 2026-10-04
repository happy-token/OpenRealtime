"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Plus, Upload, X } from "lucide-react";
import { useLanguage } from "@/components/language/language-provider";
import { readJsonResponse } from "@/lib/http-json-response";
import type { KnowledgeDocument } from "@/lib/knowledge-catalog-repository";
import styles from "./knowledge-library-screen.module.css";

type Passage = { document_id: string; title: string; excerpt: string; source_url?: string | null };
type InputKind = "text" | "file" | "url";

export function KnowledgeLibraryScreen({ onCreated }: { onCreated?: () => void } = {}) {
  const { t } = useLanguage();
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [sourceUrl, setSourceUrl] = useState("");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [passages, setPassages] = useState<Passage[]>([]);
  const [editing, setEditing] = useState<KnowledgeDocument | null>(null);
  const [preview, setPreview] = useState<KnowledgeDocument | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const [fileInputRevision, setFileInputRevision] = useState(0);
  const [editorOpen, setEditorOpen] = useState(false);
  const [inputKind, setInputKind] = useState<InputKind>("text");
  const editorRef = useRef<HTMLDialogElement>(null);
  const previewRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError("");
    void fetch("/api/knowledge", { signal: controller.signal, cache: "no-store" })
      .then(async (response) => {
        const data = await readJsonResponse<{ documents?: KnowledgeDocument[]; error?: string }>(response, "知识库读取失败");
        if (!response.ok || !data.documents) throw new Error(data.error || "知识库读取失败");
        if (!controller.signal.aborted) { setDocuments(data.documents); setSelected(data.documents.filter((doc) => doc.owner_id !== null).slice(0, 30).map((doc) => doc.document_id)); }
      }).catch((cause: unknown) => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "知识库读取失败"); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [revision]);

  useEffect(() => { if (editorOpen) editorRef.current?.showModal(); }, [editorOpen]);
  useEffect(() => { if (preview) previewRef.current?.showModal(); }, [preview]);

  function resetEditor() { setEditing(null); setTitle(""); setContent(""); setSourceUrl(""); setFile(null); setFileInputRevision((old) => old + 1); }
  function closeEditor() { editorRef.current?.close(); setEditorOpen(false); resetEditor(); }
  function openEditor(document?: KnowledgeDocument) {
    resetEditor(); setError(""); setNotice(""); setInputKind("text");
    if (document) { setEditing(document); setTitle(document.title); setContent(document.content); setSourceUrl(document.source_key?.startsWith("url:") ? document.source_key.slice(4) : document.source_url ?? ""); }
    setEditorOpen(true);
  }
  function closePreview() { previewRef.current?.close(); setPreview(null); }

  async function runMutation(url: string, init: RequestInit, returnAfterCreate = false, deletedDocument?: KnowledgeDocument) {
    setError(""); setNotice(""); setBusy(true); setPassages([]);
    try {
      const response = await fetch(url, init);
      const data = await readJsonResponse<{ document?: KnowledgeDocument; deleted?: boolean; error?: string }>(response, "资料操作失败");
      if (!response.ok) throw new Error(data.error || "资料操作失败");
      if (data.document) {
        const document = data.document;
        setDocuments((current) => [...current.filter((item) => item.document_id !== document.document_id), document]);
        setSelected((ids) => ids.includes(document.document_id) ? ids : [...ids, document.document_id]);
        setNotice(`资料已保存 · v${document.revision ?? 1}`);
      }
      if (data.deleted && deletedDocument) {
        setDocuments((current) => current.filter((item) => item.document_id !== deletedDocument.document_id));
        setSelected((ids) => ids.filter((id) => id !== deletedDocument.document_id));
        setNotice("资料已删除，所有角色关联已同步移除");
      }
      closeEditor();
      if (returnAfterCreate && onCreated) onCreated();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "资料操作失败"); }
    finally { setBusy(false); }
  }

  function removeDocument(document: KnowledgeDocument) {
    if (!window.confirm(`删除“${document.title}”？所有关联角色将无法再检索它。`)) return;
    void runMutation(`/api/knowledge/documents/${encodeURIComponent(document.document_id)}`, {
      method: "DELETE", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expectedRevision: document.revision ?? 1 }),
    }, false, document);
  }

  function loadDemo() {
    resetEditor();
    setEditorOpen(true); setInputKind("text"); setError("");
    setTitle("Demo · 星河咖啡店指南");
    setContent("星河咖啡店营业时间为每天 09:00 至 18:00。招牌饮品是桂花拿铁。外带杯可以享受九折优惠。店内提供免费 Wi-Fi，密码是 starcoffee。地址是星河路 18 号。");
    setQuery("营业时间");
    setNotice("示例已填入，点击创建资料后再检索；将营业时间改为 20:00 并保存，可验证更新效果。");
  }

  function saveText() {
    void runMutation(editing ? `/api/knowledge/documents/${encodeURIComponent(editing.document_id)}` : "/api/knowledge", {
      method: editing ? "PATCH" : "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, content, ...(editing ? { expectedRevision: editing.revision ?? 1 } : {}) }),
    }, !editing);
  }

  function importDocument(kind: "file" | "url") {
    let body: BodyInit;
    let headers: HeadersInit | undefined;
    if (kind === "file") {
      if (!file) return;
      const form = new FormData();
      form.set("file", file);
      if (title.trim()) form.set("title", title.trim());
      if (editing) { form.set("documentId", editing.document_id); form.set("expectedRevision", String(editing.revision ?? 1)); }
      body = form;
    } else {
      body = JSON.stringify({ url: sourceUrl, title, ...(editing ? { documentId: editing.document_id, expectedRevision: editing.revision ?? 1 } : {}) });
      headers = { "Content-Type": "application/json" };
    }
    void runMutation("/api/knowledge/import", { method: "POST", headers, body }, !editing);
  }

  async function search() {
    setError(""); setBusy(true); setPassages([]); setNotice("");
    try {
      const response = await fetch("/api/knowledge/search", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query, documentIds: selected }) });
      const data = await readJsonResponse<{ passages?: Passage[]; error?: string }>(response, "检索失败");
      if (!response.ok) throw new Error(data.error || "检索失败");
      setPassages(data.passages ?? []);
      if (!data.passages?.length) setNotice("所选资料没有匹配片段，请尝试原文关键词");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "检索失败"); }
    finally { setBusy(false); }
  }

  const disabled = busy || loading;
  return <div className={styles.page}>
    <header className={styles.heading}>
      <div><h2>{t("知识库")}</h2><p>{t("统一管理参考资料。在角色配置中选择要使用的知识。")}</p></div>
      <button type="button" disabled={disabled} onClick={() => openEditor()}><Plus size={16} />{t("新增资料")}</button>
    </header>
    <div className={styles.toolbar}><span>{documents.length}{t(" 份资料")}</span><div><button className={styles.secondary} type="button" disabled={disabled} onClick={loadDemo}>{t("体验示例")}</button><Link className={styles.guideButton} href="/docs/knowledge-base">{t("使用指南")}</Link></div></div>
    {notice ? <p className={styles.notice} role="status">{t(notice)}</p> : null}
    {!editorOpen && error ? <p className={styles.error} role="alert">{t(error)} <button className={styles.secondary} type="button" disabled={busy} onClick={() => setRevision((old) => old + 1)}>{t("重试")}</button></p> : null}
    <section className={styles.list} aria-label={t("资料列表")}>
      {loading ? <p role="status">{t("正在读取知识库…")}</p> : documents.length === 0 ? <p>{t("还没有资料，点击新增资料开始。")}</p> : documents.map((doc) => <article key={doc.document_id} className={styles.document}>
        <label className={styles.selection}><input aria-label={t("选择检索资料") + " " + doc.title} type="checkbox" disabled={disabled} checked={selected.includes(doc.document_id)} onChange={(event) => { setPassages([]); setSelected((old) => event.target.checked ? [...old, doc.document_id] : old.filter((id) => id !== doc.document_id)); }} /></label>
        <button type="button" className={styles.documentTitle} onClick={() => setPreview(doc)}><strong>{doc.title}</strong><small>{doc.owner_id === null ? t("共享只读示例") : t("个人资料")} · {doc.content.length}{t(" 字")} · v{doc.revision ?? 1}</small></button>
        <div className={styles.actions}><button className={styles.secondary} type="button" onClick={() => setPreview(doc)} aria-label={t("预览") + " " + doc.title}>{t("预览")}</button>{doc.owner_id !== null ? <><button className={styles.secondary} type="button" disabled={disabled} onClick={() => openEditor(doc)} aria-label={t("编辑") + " " + doc.title}>{t("编辑")}</button><button className={styles.secondary} type="button" disabled={disabled} onClick={() => removeDocument(doc)} aria-label={t("删除") + " " + doc.title}>{t("删除")}</button></> : null}</div>
      </article>)}
    </section>
    <details className={styles.searchPanel}><summary>{t("测试检索")}</summary><p>{t("勾选资料后输入关键词，查看引用片段。最多选择 30 份，勾选不会改变角色配置。")}</p><div className={styles.row}><input aria-label={t("检索问题")} placeholder={t("输入关键词或问题")} maxLength={500} value={query} onChange={(event) => setQuery(event.target.value)} /><button type="button" disabled={disabled || !query.trim() || !selected.length || selected.length > 30} onClick={() => void search()}>{t("检索")}</button></div>{selected.length > 30 ? <p role="alert">{t("最多选择 30 份资料")}</p> : null}{passages.map((item, index) => <article className={styles.passage} key={`${item.document_id}-${index}`}><strong>{item.title}</strong><p>{item.excerpt}</p></article>)}</details>
    {editorOpen ? <dialog ref={editorRef} className={styles.dialog} aria-labelledby="knowledge-editor-title" onCancel={(event) => { event.preventDefault(); if (!busy) closeEditor(); }}>
      <header><h3 id="knowledge-editor-title">{t(editing ? "编辑资料" : "新增资料")}</h3><button className={styles.iconButton} type="button" disabled={busy} aria-label={t("关闭编辑")} onClick={closeEditor}><X size={18} /></button></header>
      <fieldset disabled={busy}>
        <label>{t("资料名称")}<input autoFocus aria-label={t("资料名称")} placeholder={t("资料名称")} value={title} maxLength={120} onChange={(event) => setTitle(event.target.value)} /></label>
        <div className={styles.tabs} aria-label={t("资料输入方式")}>{(["text", "file", "url"] as const).map((kind) => <button type="button" key={kind} aria-pressed={inputKind === kind} onClick={() => setInputKind(kind)}>{t(kind === "text" ? "文本" : kind === "file" ? "文件" : "网页")}</button>)}</div>
        {inputKind === "text" ? <label>{t("资料内容")}<textarea aria-label={t("资料内容")} value={content} onChange={(event) => setContent(event.target.value)} rows={10} placeholder={t("粘贴原文，可增删或修改段落")} /></label> : null}
        {inputKind === "file" ? <div><p>{t("支持文字型 PDF、DOCX、TXT、Markdown；文件最多 5 MB。")}</p><label className={styles.filePicker}><Upload size={16} />{t("选择文件")}<input key={fileInputRevision} aria-label={t("选择资料文件")} type="file" accept=".pdf,.docx,.txt,.md" onChange={(event) => setFile(event.target.files?.[0] ?? null)} /></label><span className={styles.fileName}>{file?.name ?? t("未选择文件")}</span></div> : null}
        {inputKind === "url" ? <label>{t("公开网页地址")}<input aria-label={t("公开网页地址")} type="url" placeholder="https://example.com/article" value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} /><small>{t("支持公开 HTTPS 正文页，不支持需登录或动态加载的页面。")}</small></label> : null}
        <p className={styles.hint}>{t("正文最多 32 KB。修改保存后，所有关联角色使用新版本。")}</p>
      </fieldset>
      {notice ? <p className={styles.notice} role="status">{t(notice)}</p> : null}{error ? <p className={styles.error} role="alert">{t(error)}</p> : null}
      <footer><button type="button" className={styles.secondary} disabled={busy} onClick={closeEditor}>{t("取消")}</button><button type="button" disabled={busy || (inputKind === "text" ? !title.trim() || !content.trim() : inputKind === "file" ? !file : !sourceUrl.trim())} onClick={() => inputKind === "text" ? saveText() : importDocument(inputKind)}>{busy ? t("正在保存…") : t(editing ? "保存修改" : "创建资料")}</button></footer>
    </dialog> : null}
    {preview ? <dialog ref={previewRef} className={styles.dialog} aria-labelledby="knowledge-preview-title" onCancel={(event) => { event.preventDefault(); closePreview(); }}><header><h3 id="knowledge-preview-title">{preview.title}</h3><button className={styles.iconButton} type="button" aria-label={t("关闭预览")} onClick={closePreview}><X size={18} /></button></header><p className={styles.hint}>{preview.content.length}{t(" 字")} · v{preview.revision ?? 1}</p><div className={styles.fullText}>{preview.content}</div>{preview.source_url ? <a href={preview.source_url} target="_blank" rel="noopener noreferrer">{t("查看原网页")}</a> : null}<footer><button type="button" className={styles.secondary} onClick={closePreview}>{t("关闭")}</button>{preview.owner_id !== null ? <button type="button" disabled={disabled} onClick={() => { const document = preview; closePreview(); openEditor(document); }}>{t("编辑资料")}</button> : null}</footer></dialog> : null}
  </div>;
}

"use client";

import { useEffect, useState } from "react";
import { readJsonResponse } from "@/lib/http-json-response";
import type { KnowledgeDocument } from "@/lib/knowledge-catalog-repository";
import styles from "./knowledge-library-screen.module.css";

type Passage = { document_id: string; title: string; excerpt: string; source_url?: string | null };

export function KnowledgeLibraryScreen({ onCreated }: { onCreated?: () => void } = {}) {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [sourceUrl, setSourceUrl] = useState("");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [passages, setPassages] = useState<Passage[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/knowledge", { signal: controller.signal, cache: "no-store" })
      .then((response) => readJsonResponse<{ documents?: KnowledgeDocument[]; error?: string }>(response, "知识库读取失败"))
      .then((data) => { if (!controller.signal.aborted) setDocuments(data.documents ?? []); })
      .catch((cause) => { if (!controller.signal.aborted) setError(String(cause)); });
    return () => controller.abort();
  }, []);

  async function addDocument() {
    setError(""); setBusy(true);
    try {
      const response = await fetch("/api/knowledge", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title, content }) });
      const data = await readJsonResponse<{ document?: KnowledgeDocument; error?: string }>(response, "资料创建失败");
      if (!response.ok || !data.document) throw new Error(data.error || "资料创建失败");
      if (onCreated) { onCreated(); return; }
      setDocuments((current) => [...current, data.document!]);
      setContent(""); setTitle("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "资料创建失败"); }
    finally { setBusy(false); }
  }

  async function importDocument(kind: "file" | "url") {
    setError(""); setBusy(true);
    try {
      let body: BodyInit;
      let headers: HeadersInit | undefined;
      if (kind === "file") {
        if (!file) return;
        const form = new FormData();
        form.set("file", file);
        if (title.trim()) form.set("title", title.trim());
        body = form;
      } else {
        body = JSON.stringify({ url: sourceUrl, title });
        headers = { "Content-Type": "application/json" };
      }
      const response = await fetch("/api/knowledge/import", { method: "POST", headers, body });
      const data = await readJsonResponse<{ document?: KnowledgeDocument; error?: string }>(response, "资料导入失败");
      if (!response.ok || !data.document) throw new Error(data.error || "资料导入失败");
      if (onCreated) { onCreated(); return; }
      setDocuments((current) => [...current, data.document!]);
      setFile(null); setSourceUrl(""); setTitle("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "资料导入失败"); }
    finally { setBusy(false); }
  }

  async function search() {
    setError(""); setBusy(true); setPassages([]);
    try {
      const response = await fetch("/api/knowledge/search", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ query, documentIds: selected }) });
      const data = await readJsonResponse<{ passages?: Passage[]; error?: string }>(response, "检索失败");
      if (!response.ok) throw new Error(data.error || "检索失败");
      setPassages(data.passages ?? []);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "检索失败"); }
    finally { setBusy(false); }
  }

  return <div className={styles.page}>
    <header><h2>知识库</h2><p>私人资料仅对当前用户可见；绑定到角色后，会话才可检索。共享示例用于体验，不会修改你的资料。</p></header>
    <div className={styles.columns}>
      <section><h3>资料列表</h3>{documents.map((doc) => <label key={doc.document_id} className={styles.document}>
        <input type="checkbox" checked={selected.includes(doc.document_id)} onChange={(event) => setSelected((old) => event.target.checked ? [...old, doc.document_id] : old.filter((id) => id !== doc.document_id))} />
        <span><strong>{doc.title}</strong><small>{doc.owner_id === null ? "共享只读示例" : "私人资料"} · {doc.content.length} 字</small><em>{doc.content.slice(0, 120)}</em></span>
      </label>)}
      <h3>测试检索</h3><div className={styles.row}><input aria-label="检索问题" placeholder="输入问题，在勾选的资料中检索" value={query} onChange={(event) => setQuery(event.target.value)} /><button type="button" disabled={busy || !query.trim() || !selected.length} onClick={() => void search()}>检索</button></div>
      {passages.map((item, index) => <details className={styles.passsage} key={`${item.document_id}-${index}`}><summary>{item.title} · 查看引用片段</summary>{item.source_url ? <a href={item.source_url} target="_blank" rel="noopener noreferrer">查看原网页</a> : null}<p>{item.excerpt}</p></details>)}
      </section>
      <section><h3>导入资料</h3><p>支持 PDF、DOCX、Markdown、TXT、粘贴文本和公开 HTTPS 网页。提取的文本最多 32 KB。</p>
        <input aria-label="资料名称" placeholder="资料名称" value={title} maxLength={120} onChange={(event) => setTitle(event.target.value)} />
        <input aria-label="选择资料文件" type="file" accept=".pdf,.docx,.txt,.md,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
        <button type="button" disabled={busy || !file} onClick={() => void importDocument("file")}>导入文件</button>
        <h3>导入网页</h3><div className={styles.row}><input aria-label="公开网页地址" type="url" placeholder="https://example.com/article" value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} /><button type="button" disabled={busy || !sourceUrl.trim()} onClick={() => void importDocument("url")}>导入网页</button></div>
        <h3>粘贴文本</h3>
        <textarea aria-label="资料内容" placeholder="粘贴资料原文" value={content} onChange={(event) => setContent(event.target.value)} rows={12} />
        <button type="button" disabled={busy || !title.trim() || !content.trim()} onClick={() => void addDocument()}>创建资料</button>
      </section>
    </div>
    {error ? <p className={styles.error} role="alert">{error}</p> : null}
  </div>;
}

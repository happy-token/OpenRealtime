"use client";

import Link from "next/link";
import { Check, ChevronDown, LoaderCircle, PlugZap, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import type { PersonalKeyProvider } from "@/lib/user-provider-credentials";
import styles from "./provider-settings-screen.module.css";

type ProviderItem = { id: PersonalKeyProvider; name: string; detail: string; testable?: boolean };
type KeyStatus = { provider: PersonalKeyProvider; configured: boolean; platformConfigured: boolean; suffix?: string; updatedAt?: string };
type Feedback = { ok: boolean; message: string };

const GROUPS: { title: string; description: string; items: ProviderItem[] }[] = [
  { title: "语音供应商", description: "连接语音识别与语音合成服务。", items: [
    { id: "doubao", name: "豆包语音", detail: "语音识别与合成 · 火山引擎", testable: true },
    { id: "dashscope", name: "阿里云百炼", detail: "CosyVoice 语音合成 · 百炼模型共用凭证", testable: true },
  ] },
  { title: "LLM 供应商", description: "最近保存的个人 LLM Key 将用于新语音会话；百炼 Qwen 的模型切换尚未接入。", items: [
    { id: "deepseek", name: "DeepSeek", detail: "DeepSeek 对话模型", testable: true },
    { id: "openai", name: "OpenAI", detail: "OpenAI 对话模型", testable: true },
  ] },
  { title: "其他服务", description: "数字人与视频生成服务的凭证也在这里管理。", items: [
    { id: "anam", name: "Anam", detail: "实时数字人" },
    { id: "minimax", name: "MiniMax", detail: "视频生成" },
  ] },
];

export function ProviderCredentialManager() {
  const [statuses, setStatuses] = useState<KeyStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [signedOut, setSignedOut] = useState(false);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<PersonalKeyProvider | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState<PersonalKeyProvider | null>(null);
  const [feedback, setFeedback] = useState<Partial<Record<PersonalKeyProvider, Feedback>>>({});

  const refresh = useCallback(async () => {
    const response = await fetch("/api/user/provider-keys", { cache: "no-store" });
    if (response.status === 401) { setSignedOut(true); setLoadFailed(false); return; }
    const payload = await response.json() as { credentials?: KeyStatus[]; error?: string };
    if (!response.ok || !payload.credentials) throw new Error(payload.error || "无法读取供应商配置");
    setStatuses(payload.credentials);
    setSignedOut(false);
    setLoadFailed(false);
  }, []);

  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("loginError") === "provider") {
      setError("登录服务暂时无法连接，请稍后重试。");
    }
    void refresh().catch((cause: unknown) => { setLoadFailed(true); setError(cause instanceof Error ? cause.message : "无法读取供应商配置"); })
      .finally(() => setLoading(false));
  }, [refresh]);

  function setResult(provider: PersonalKeyProvider, result: Feedback) {
    setFeedback((current) => ({ ...current, [provider]: result }));
  }

  async function save(event: FormEvent, provider: PersonalKeyProvider) {
    event.preventDefault();
    if (busy || !draft.trim()) return;
    setBusy(provider);
    setResult(provider, { ok: true, message: "" });
    try {
      const response = await fetch("/api/user/provider-keys", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, apiKey: draft.trim() }),
      });
      const payload = await response.json() as { error?: string };
      if (!response.ok) throw new Error(payload.error || "保存失败");
      setDraft("");
      setEditing(null);
      await refresh();
      setResult(provider, { ok: true, message: "已保存凭证，可点击测试连接" });
    } catch (cause) {
      setResult(provider, { ok: false, message: cause instanceof Error ? cause.message : "保存失败" });
    } finally { setBusy(null); }
  }

  async function test(provider: PersonalKeyProvider) {
    if (busy) return;
    setBusy(provider);
    setResult(provider, { ok: true, message: "正在测试连接…" });
    try {
      const response = await fetch("/api/user/provider-keys/test", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, ...(editing === provider && draft.trim() ? { apiKey: draft.trim() } : {}) }),
      });
      const payload = await response.json() as { ok?: boolean; message?: string; error?: string };
      setResult(provider, { ok: response.ok && payload.ok === true, message: payload.message || payload.error || "测试失败" });
    } catch {
      setResult(provider, { ok: false, message: "连接失败，请稍后重试" });
    } finally { setBusy(null); }
  }

  async function remove(provider: PersonalKeyProvider) {
    if (busy || !window.confirm("删除这个供应商的个人 API Key？")) return;
    setBusy(provider);
    try {
      const response = await fetch(`/api/user/provider-keys?provider=${encodeURIComponent(provider)}`, { method: "DELETE" });
      const payload = await response.json() as { error?: string };
      if (!response.ok) throw new Error(payload.error || "删除失败");
      await refresh();
      setResult(provider, { ok: true, message: "凭证已删除" });
    } catch (cause) {
      setResult(provider, { ok: false, message: cause instanceof Error ? cause.message : "删除失败" });
    } finally { setBusy(null); }
  }

  const activeLlm = statuses.filter((entry) => entry.configured && (entry.provider === "deepseek" || entry.provider === "openai"))
    .sort((left, right) => (right.updatedAt ?? "").localeCompare(left.updatedAt ?? "") || left.provider.localeCompare(right.provider))[0]?.provider;

  function card(item: ProviderItem) {
    const status = statuses.find((entry) => entry.provider === item.id);
    const current = feedback[item.id];
    const isEditing = editing === item.id;
    const isBusy = busy === item.id;
    const state = signedOut ? "登录后查看" : loading ? "正在读取" : loadFailed ? "状态未知" : status?.configured && activeLlm === item.id ? "当前使用" : status?.configured ? "已配置" : status?.platformConfigured ? "平台已配置" : "未配置";
    return <details className={styles.card} key={item.id}>
      <summary className={styles.cardTop}>
        <div className={styles.providerIdentity}>
          <span className={styles.providerMark}>{item.name.slice(0, 1)}</span>
          <div><h3>{item.name}</h3><p>{item.detail}</p></div>
        </div>
        <span className={styles.state} data-configured={Boolean(status?.configured)}>{state}</span>
        <ChevronDown className={styles.disclosureIcon} aria-hidden="true" />
      </summary>
      <div className={styles.cardBody}>
      {!signedOut && !loading && !loadFailed && <>
        <div className={styles.credentialLine}>{status?.configured ? `个人 Key ····${status.suffix ?? ""}` : status?.platformConfigured ? "当前使用平台提供的 Key" : "尚未添加个人 Key"}</div>
        {isEditing ? <form className={styles.form} onSubmit={(event) => void save(event, item.id)}>
          <label htmlFor={`provider-key-${item.id}`}>{item.name} API Key</label>
          <input id={`provider-key-${item.id}`} type="password" autoComplete="off" value={draft}
            onChange={(event) => setDraft(event.target.value)} placeholder="粘贴 API Key" />
          <div className={styles.actions}>
            <button type="submit" disabled={Boolean(busy) || !draft.trim()}>{isBusy ? <LoaderCircle className={styles.spin} /> : <Check />}保存</button>
            {item.testable && <button type="button" className={styles.secondary} disabled={Boolean(busy) || !draft.trim()} onClick={() => void test(item.id)}><PlugZap />测试</button>}
            <button type="button" className={styles.secondary} disabled={Boolean(busy)} onClick={() => { setEditing(null); setDraft(""); }}>取消</button>
          </div>
        </form> : <div className={styles.actions}>
          <button type="button" disabled={Boolean(busy)} onClick={() => { setEditing(item.id); setDraft(""); setFeedback((current) => ({ ...current, [item.id]: undefined })); }}>
            {status?.configured ? "更换 Key" : "添加 Key"}
          </button>
          {item.testable && status?.configured && <button type="button" className={styles.secondary} disabled={Boolean(busy)} onClick={() => void test(item.id)}>
            {isBusy ? <LoaderCircle className={styles.spin} /> : <PlugZap />}测试连接
          </button>}
          {status?.configured && <button type="button" className={`${styles.secondary} ${styles.delete}`} disabled={Boolean(busy)} onClick={() => void remove(item.id)}><Trash2 />删除</button>}
        </div>}
      </>}
      {current?.message && <p className={styles.feedback} data-ok={current.ok} role="status">{current.message}</p>}
      </div>
    </details>;
  }

  return <div className={styles.manager}>
    {signedOut && <div className={styles.authNotice}>登录后可查看配置状态并保存个人凭证。<Link href="/api/user/login?next=/settings/providers">登录</Link></div>}
    {error && <div className={styles.error} role="alert">{error}{loadFailed && <button type="button" onClick={() => {
      setLoading(true); setError("");
      void refresh().catch((cause: unknown) => { setLoadFailed(true); setError(cause instanceof Error ? cause.message : "无法读取供应商配置"); })
        .finally(() => setLoading(false));
    }}>重试</button>}</div>}
    {GROUPS.map((group) => <section className={styles.group} aria-label={group.title} key={group.title}>
      <div className={styles.groupHeading}><h2>{group.title}</h2><p>{group.description}</p></div>
      <div className={styles.cards}>{group.items.map(card)}</div>
    </section>)}
    <p className={styles.footnote}>凭证在服务端加密保存。连接测试会向对应供应商发送请求；豆包语音测试会合成一小段语音，可能产生少量用量。</p>
  </div>;
}

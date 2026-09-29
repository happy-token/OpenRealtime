"use client";
import { useLanguage } from "@/components/language/language-provider";


import Link from "next/link";
import { Check, ChevronDown, LoaderCircle, PlugZap, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import type { PersonalKeyProvider } from "@/lib/user-provider-credentials";
import styles from "./provider-settings-screen.module.css";

type ProviderItem = { id: PersonalKeyProvider; name: string; detail: string; testable?: boolean };
type KeyStatus = { provider: PersonalKeyProvider; configured: boolean; platformConfigured: boolean; suffix?: string; updatedAt?: string };
type Feedback = { ok: boolean; message: string };

const GROUPS: { title: string; description: string; items: ProviderItem[] }[] = [
  { title: "ASR · 语音识别", description: "实时识别需要持续输出中间文本与最终文本。当前页面管理凭证，ASR 能力测试将在 bridge 契约接入后开放。", items: [
    { id: "doubao", name: "豆包 ASR", detail: "流式语音识别 · 与豆包 TTS 共用 Key" },
  ] },
  { title: "TTS · 语音合成", description: "实时播报要求文本输入和音频输出双流式；现有连接测试只验证供应商接口，不代表完整双流式契约通过。", items: [
    { id: "doubao", name: "豆包 TTS", detail: "双流式语音合成 · 与豆包 ASR 共用 Key", testable: true },
    { id: "dashscope", name: "阿里云百炼 TTS", detail: "双流式语音合成 · CosyVoice", testable: true },
  ] },
  { title: "LLM · 对话模型", description: "最近保存的个人 LLM Key 将用于新语音会话；显式多实例切换仍在开发中。", items: [
    { id: "deepseek", name: "DeepSeek", detail: "DeepSeek 对话模型", testable: true },
    { id: "openai", name: "OpenAI", detail: "OpenAI 对话模型", testable: true },
  ] },
  { title: "其他服务", description: "数字人与视频生成服务的凭证也在这里管理。", items: [
    { id: "anam", name: "Anam", detail: "实时数字人" },
    { id: "minimax", name: "MiniMax", detail: "视频生成" },
  ] },
];

export function ProviderCredentialManager({ mode = "all" }: { mode?: "all" | "other" }) {
  const { t } = useLanguage();
  const [statuses, setStatuses] = useState<KeyStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [signedOut, setSignedOut] = useState(false);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState<PersonalKeyProvider | null>(null);
  const [feedback, setFeedback] = useState<Record<string, Feedback | undefined>>({});

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

  function setResult(item: ProviderItem, result: Feedback) {
    setFeedback((current) => ({ ...current, [item.name]: result }));
  }

  async function save(event: FormEvent, item: ProviderItem) {
    event.preventDefault();
    if (busy || !draft.trim()) return;
    const provider = item.id;
    setBusy(provider);
    setResult(item, { ok: true, message: "" });
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
      setResult(item, { ok: true, message: item.testable ? "已保存凭证，可点击测试连接" : "凭证已保存；此能力尚无独立连接测试" });
    } catch (cause) {
      setResult(item, { ok: false, message: cause instanceof Error ? cause.message : "保存失败" });
    } finally { setBusy(null); }
  }

  async function test(item: ProviderItem) {
    if (busy) return;
    const provider = item.id;
    setBusy(provider);
    setResult(item, { ok: true, message: "正在测试连接…" });
    try {
      const response = await fetch("/api/user/provider-keys/test", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, ...(editing === item.name && draft.trim() ? { apiKey: draft.trim() } : {}) }),
      });
      const payload = await response.json() as { ok?: boolean; message?: string; error?: string };
      setResult(item, { ok: response.ok && payload.ok === true, message: payload.message || payload.error || "测试失败" });
    } catch {
      setResult(item, { ok: false, message: "连接失败，请稍后重试" });
    } finally { setBusy(null); }
  }

  async function remove(item: ProviderItem) {
    if (busy || !window.confirm("删除这个供应商的个人 API Key？")) return;
    const provider = item.id;
    setBusy(provider);
    try {
      const response = await fetch(`/api/user/provider-keys?provider=${encodeURIComponent(provider)}`, { method: "DELETE" });
      const payload = await response.json() as { error?: string };
      if (!response.ok) throw new Error(payload.error || "删除失败");
      await refresh();
      setResult(item, { ok: true, message: "凭证已删除" });
    } catch (cause) {
      setResult(item, { ok: false, message: cause instanceof Error ? cause.message : "删除失败" });
    } finally { setBusy(null); }
  }

  const activeLlm = statuses.filter((entry) => entry.configured && (entry.provider === "deepseek" || entry.provider === "openai"))
    .sort((left, right) => (right.updatedAt ?? "").localeCompare(left.updatedAt ?? "") || left.provider.localeCompare(right.provider))[0]?.provider;

  function card(item: ProviderItem) {
    const status = statuses.find((entry) => entry.provider === item.id);
    const current = feedback[item.name];
    const isEditing = editing === item.name;
    const isBusy = busy === item.id;
    const state = signedOut ? "登录后查看" : loading ? "正在读取" : loadFailed ? "状态未知" : status?.configured && activeLlm === item.id && (item.id === "deepseek" || item.id === "openai") ? "自动选用" : status?.configured ? "Key 已保存" : status?.platformConfigured ? "平台有 Key" : "未配置";
    return <details className={styles.card} key={item.id}>
      <summary className={styles.cardTop}>
        <div className={styles.providerIdentity}>
          <span className={styles.providerMark}>{item.name.slice(0, 1)}</span>
          <div><h3>{item.name}</h3><p>{item.detail}</p></div>
        </div>
        <span className={styles.state} data-configured={Boolean(status?.configured)}>{t(state)}</span>
        <ChevronDown className={styles.disclosureIcon} aria-hidden="true" />
      </summary>
      <div className={styles.cardBody}>
      {!signedOut && !loading && !loadFailed && <>
        <div className={styles.credentialLine}>{status?.configured ? t("个人 Key ····") + (status.suffix ?? "") + "" : status?.platformConfigured ? t("当前使用平台提供的 Key") : t("尚未添加个人 Key")}</div>
        {isEditing ? <form className={styles.form} onSubmit={(event) => void save(event, item)}>
          <label htmlFor={`provider-key-${item.id}-${item.name}`}>{item.name} API Key</label>
          <input id={`provider-key-${item.id}-${item.name}`} type="password" autoComplete="off" value={draft}
            onChange={(event) => setDraft(event.target.value)} placeholder={t("粘贴 API Key")} />
          <div className={styles.actions}>
            <button type="submit" disabled={Boolean(busy) || !draft.trim()}>{isBusy ? <LoaderCircle className={styles.spin} /> : <Check />}{t("保存")}</button>
            {item.testable && <button type="button" className={styles.secondary} disabled={Boolean(busy) || !draft.trim()} onClick={() => void test(item)}><PlugZap />{t("测试")}</button>}
            <button type="button" className={styles.secondary} disabled={Boolean(busy)} onClick={() => { setEditing(null); setDraft(""); }}>{t("取消")}</button>
          </div>
        </form> : <div className={styles.actions}>
          <button type="button" disabled={Boolean(busy)} onClick={() => { setEditing(item.name); setDraft(""); setFeedback((current) => ({ ...current, [item.name]: undefined })); }}>
            {status?.configured ? t("更换 Key") : t("添加 Key")}
          </button>
          {item.testable && status?.configured && <button type="button" className={styles.secondary} disabled={Boolean(busy)} onClick={() => void test(item)}>
            {isBusy ? <LoaderCircle className={styles.spin} /> : <PlugZap />}{t("测试连接")}</button>}
          {status?.configured && <button type="button" className={`${styles.secondary} ${styles.delete}`} disabled={Boolean(busy)} onClick={() => void remove(item)}><Trash2 />{t("删除")}</button>}
        </div>}
      </>}
      {current?.message && <p className={styles.feedback} data-ok={current.ok} role="status">{current.message}</p>}
      </div>
    </details>;
  }

  return <div className={styles.manager}>
    {signedOut && <div className={styles.authNotice}>{t("登录后可查看配置状态并保存个人凭证。")}<Link href="/api/user/login?next=/settings/providers">{t("登录")}</Link></div>}
    {error && <div className={styles.error} role="alert">{t(error)}{loadFailed && <button type="button" onClick={() => {
      setLoading(true); setError("");
      void refresh().catch((cause: unknown) => { setLoadFailed(true); setError(cause instanceof Error ? cause.message : "无法读取供应商配置"); })
        .finally(() => setLoading(false));
    }}>{t("重试")}</button>}</div>}
    {mode === "other" ? <div className={styles.cards} aria-label={t("高级服务")}>{GROUPS[3].items.map(card)}</div>
      : GROUPS.map((group) => <section className={styles.group} aria-label={group.title} key={group.title}>
      <div className={styles.groupHeading}><h2>{group.title}</h2><p>{group.description}</p></div>
      <div className={styles.cards}>{group.items.map(card)}</div>
    </section>)}
    <p className={styles.footnote}>{mode === "other" ? t("服务凭证在服务端加密保存，仅用于各自的数字人或视频生成能力。")
      : t("凭证在服务端加密保存。连接测试会向对应供应商发送请求；豆包语音测试会合成一小段语音，可能产生少量用量。")}</p>
  </div>;
}

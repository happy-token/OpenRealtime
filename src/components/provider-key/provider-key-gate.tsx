"use client";
import { useLanguage } from "@/components/language/language-provider";


import { KeyRound, LoaderCircle, X } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import type { UserKeyProvider } from "@/lib/provider-api-key";
import styles from "./provider-key-gate.module.css";

type PendingRequest = { provider: UserKeyProvider; resolve: (ready: boolean) => void };
const KeyGateContext = createContext<((provider: UserKeyProvider, replace?: boolean) => Promise<boolean>) | null>(null);

export function useProviderKeyGate() {
  const gate = useContext(KeyGateContext);
  if (!gate) throw new Error("ProviderKeyGate is missing");
  return gate;
}

export function ProviderKeyGate({ children }: { children: ReactNode }) {
  const { t } = useLanguage();
  const [pending, setPending] = useState<PendingRequest | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const pendingRef = useRef<PendingRequest | null>(null);

  const finish = useCallback((ready: boolean) => {
    pendingRef.current?.resolve(ready);
    pendingRef.current = null;
    setPending(null);
    setApiKey("");
    setError("");
    setSaving(false);
    if (dialog.current?.open) dialog.current.close();
  }, []);

  useEffect(() => {
    if (pending && dialog.current && !dialog.current.open) dialog.current.showModal();
  }, [pending]);

  const ensureKey = useCallback(async (provider: UserKeyProvider, replace = false): Promise<boolean> => {
    if (!replace) {
      const response = await fetch(`/api/provider-key?provider=${provider}`, { cache: "no-store" });
      const status = await response.json() as { configured?: boolean; error?: string };
      if (!response.ok) throw new Error(status.error || "无法检查 API Key");
      if (status.configured) return true;
    }
    if (pendingRef.current) return false;
    return new Promise<boolean>((resolve) => {
      const next = { provider, resolve };
      pendingRef.current = next;
      setPending(next);
    });
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!pending || saving || !apiKey.trim()) return;
    setSaving(true);
    setError("");
    try {
      const response = await fetch("/api/provider-key", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: pending.provider, apiKey: apiKey.trim() }),
      });
      const result = await response.json() as { error?: string };
      if (!response.ok) throw new Error(result.error || "API Key 保存失败");
      finish(true);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "API Key 保存失败");
      setSaving(false);
    }
  }

  return <KeyGateContext.Provider value={ensureKey}>
    {children}
    {pending && <dialog ref={dialog} className={styles.dialog} aria-labelledby="provider-key-title"
      onClose={() => finish(false)} onCancel={(event) => { if (saving) event.preventDefault(); }}
      onPointerDown={(event) => { if (event.target === event.currentTarget && !saving) finish(false); }}>
      <form onSubmit={(event) => void submit(event)}>
        <header className={styles.header}>
          <span className={styles.icon}><KeyRound aria-hidden="true" /></span>
          <button type="button" aria-label={t("关闭 API Key 弹窗")} disabled={saving} onClick={() => finish(false)}><X aria-hidden="true" /></button>
        </header>
        <h2 id="provider-key-title">{t("连接 ")}{pending.provider === "anam" ? t("Anam 实时数字人") : t("MiniMax 视频生成")}</h2>
        <p>{pending.provider === "anam" ? t("使用你自己的 Anam API Key 启动实时数字人。") : t("视频生成将消耗你自己的 MiniMax 额度。")}</p>
        <label htmlFor="provider-api-key">API Key</label>
        <input id="provider-api-key" type="password" autoComplete="off" autoFocus
          value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={t("输入 API Key")} />
        {pending.provider === "anam" && <a href="https://anam.ai/" target="_blank" rel="noopener noreferrer">{t("申请 Anam API Key · 了解免费体验额度")}</a>}
        {error && <p className={styles.error} role="alert">{t(error)}</p>}
        <footer>
          <button type="button" className={styles.cancel} disabled={saving} onClick={() => finish(false)}>{t("取消")}</button>
          <button type="submit" className={styles.confirm} disabled={saving || !apiKey.trim()}>
            {saving && <LoaderCircle className={styles.spin} aria-hidden="true" />}{saving ? t("正在保存") : t("继续")}
          </button>
        </footer>
      </form>
    </dialog>}
  </KeyGateContext.Provider>;
}

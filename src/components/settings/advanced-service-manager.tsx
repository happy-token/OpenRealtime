"use client";
import { useLanguage } from "@/components/language/language-provider";

import { SelectMenu } from "@/components/ui/select-menu";

import { Check, Pencil, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { PROVIDER_SCOPE_DISPLAY_ORDER } from "./provider-scope-order";
import styles from "./provider-settings-screen.module.css";

type ServiceCapability = "realtime-avatar" | "video-generation";
type ServiceProvider = "anam" | "minimax";
type KeyStatus = { provider: ServiceProvider; configured: boolean; platformConfigured: boolean;
  suffix?: string; platformSuffix?: string };
type ServiceCatalogEntry = { id: ServiceProvider; name: string; capability: ServiceCapability;
  description: string; keyUrl: string };

const CAPABILITIES: { id: ServiceCapability; title: string; description: string }[] = [
  { id: "realtime-avatar", title: "实时数字人", description: "驱动可实时对话的数字人形象" },
  { id: "video-generation", title: "视频生成", description: "生成数字人视频素材" },
];

// Add a provider here only after its runtime integration and key resolver are available.
const CATALOG: ServiceCatalogEntry[] = [
  { id: "anam", name: "Anam", capability: "realtime-avatar",
    description: "提供实时数字人会话与形象服务", keyUrl: "https://anam.ai/" },
  { id: "minimax", name: "MiniMax", capability: "video-generation",
    description: "提供视频生成服务", keyUrl: "https://platform.minimaxi.com/" },
];

export function AdvancedServiceManager() {
  const { t } = useLanguage();
  const [statuses, setStatuses] = useState<KeyStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [signedOut, setSignedOut] = useState(false);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<{ capability: ServiceCapability; provider: ServiceProvider; key: string } | null>(null);

  const refresh = useCallback(async () => {
    const response = await fetch("/api/user/provider-keys", { cache: "no-store" });
    if (response.status === 401) { setSignedOut(true); return; }
    const payload = await response.json() as { credentials?: KeyStatus[]; error?: string };
    if (!response.ok || !payload.credentials) throw new Error(payload.error || "无法读取高级服务配置");
    setStatuses(payload.credentials);
    setSignedOut(false);
    setError("");
  }, []);

  useEffect(() => {
    void refresh().catch((cause: unknown) => setError(cause instanceof Error ? cause.message : "读取失败"))
      .finally(() => setLoading(false));
  }, [refresh]);

  function startCreate(capability: ServiceCapability) {
    const available = CATALOG.find((entry) => entry.capability === capability && !statuses.find(
      (status) => status.provider === entry.id && status.configured));
    if (!available) return;
    setDraft({ capability, provider: available.id, key: "" });
    setError(""); setFeedback("");
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!draft || busy) return;
    setBusy(true); setError(""); setFeedback("");
    try {
      const response = await fetch("/api/user/provider-keys", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: draft.provider, apiKey: draft.key.trim() }) });
      const payload = await response.json() as { error?: string };
      if (!response.ok) throw new Error(payload.error || "保存失败");
      const name = CATALOG.find((entry) => entry.id === draft.provider)?.name ?? "供应商";
      setDraft(null);
      await refresh();
      setFeedback(`${name} 个人配置已保存，后续会话优先使用个人 Key。`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "保存失败"); }
    finally { setBusy(false); }
  }

  async function remove(entry: ServiceCatalogEntry) {
    if (busy || !window.confirm(`删除 ${entry.name} 的个人 API Key？新会话将改用平台配置（如有）。`)) return;
    setBusy(true); setError(""); setFeedback("");
    try {
      const response = await fetch(`/api/user/provider-keys?provider=${entry.id}`, { method: "DELETE" });
      const payload = await response.json() as { error?: string };
      if (!response.ok) throw new Error(payload.error || "删除失败");
      await refresh();
      setFeedback(`${entry.name} 个人配置已删除。`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "删除失败"); }
    finally { setBusy(false); }
  }

  const selectedEntry = draft ? CATALOG.find((entry) => entry.id === draft.provider) : null;
  return <div className={styles.manager}>
    {signedOut && <p className={styles.authNotice}>{t("登录后可添加个人高级服务配置。")}<Link href="/api/user/login?next=/settings/providers">{t("登录")}</Link></p>}
    {error && <p className={styles.error} role="alert">{t(error)}</p>}
    {feedback && <p className={styles.authNotice} role="status">{feedback}</p>}
    {CAPABILITIES.map((capability) => {
      const providers = CATALOG.filter((entry) => entry.capability === capability.id);
      const personal = providers.filter((entry) => statuses.find((status) => status.provider === entry.id && status.configured));
      const platform = providers.filter((entry) => statuses.find((status) => status.provider === entry.id && status.platformConfigured));
      const canCreate = providers.some((entry) => !statuses.find((status) => status.provider === entry.id && status.configured));
      return <section className={styles.group} aria-label={capability.title} key={capability.id}>
        <div className={styles.instanceHeading}><div><h2>{capability.title}</h2><p>{capability.description}</p></div>
          <button className={styles.addProviderButton} type="button" disabled={loading || signedOut || busy || !canCreate}
            onClick={() => startCreate(capability.id)}><Plus aria-hidden="true" />{t("新建供应商")}</button></div>
        <div className={styles.scopeGroups}>{PROVIDER_SCOPE_DISPLAY_ORDER.map((scope) => {
          const entries = scope === "personal" ? personal : platform;
          return <div className={styles.scopeGroup} key={scope}>
            <div className={styles.scopeHeading}><h3>{scope === "personal" ? t("我的配置") : t("平台配置")}</h3><span>{loading ? t("读取中…") : entries.length ? "" + (entries.length) + t(" 项") : t("未配置")}</span></div>
            {loading ? <p className={styles.emptyInstances}>{t("正在读取配置…")}</p> : entries.length === 0
              ? <p className={styles.emptyInstances}>{scope === "personal" ? t("暂无个人配置") : t("暂无平台配置")}</p>
              : <div className={styles.instanceList}>{entries.map((entry) => {
                const status = statuses.find((item) => item.provider === entry.id)!;
                const active = scope === "personal";
                return <article className={styles.instanceCard} data-selected={active} key={`${scope}:${entry.id}`}>
                  <div className={styles.instanceMeta}><div className={styles.instanceIdentity}>
                    <h4>{entry.name}</h4><span>{entry.description}</span>
                    <span>Key ····{scope === "personal" ? status.suffix : status.platformSuffix}</span>
                  </div><div className={styles.instanceBadges}>
                    {active && <span className={styles.state} data-configured="true">{t("个人优先")}</span>}
                    <span className={styles.state}>{scope === "personal" ? t("个人 Key") : t("平台 Key")}</span>
                  </div></div>
                  {scope === "personal" && <div className={styles.instanceActions}>
                    <button type="button" disabled={busy} onClick={() => { setDraft({ capability: capability.id, provider: entry.id, key: "" }); setError(""); }}><Pencil />{t("编辑")}</button>
                    <button type="button" disabled={busy} onClick={() => void remove(entry)}><Trash2 />{t("删除")}</button>
                  </div>}
                </article>;
              })}</div>}
          </div>;
        })}</div>
      </section>;
    })}
    <p className={styles.footnote}>{t("平台配置只读。Anam 等服务优先使用个人 Key；个人视频生成任务需要个人 MiniMax Key。当前每个供应商支持一组个人 Key，新增供应商需先完成对应的服务接入。")}</p>
    {draft && selectedEntry && <div className={styles.instanceDialogBackdrop} role="presentation"
      onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) setDraft(null); }}>
      <div className={styles.instanceDialog} role="dialog" aria-modal="true" aria-labelledby="advanced-service-dialog-title">
        <h2 id="advanced-service-dialog-title">{statuses.find((status) => status.provider === draft.provider && status.configured)
          ? t("编辑供应商") : t("新建供应商")}</h2>
        <form className={styles.instanceForm} onSubmit={(event) => void save(event)}>
          <label>{t("供应商")}<SelectMenu fullWidth value={String(draft.provider)} ariaLabel={t("供应商")} options={[...(CATALOG.filter((entry) => entry.capability === draft.capability && (entry.id === draft.provider
              || !statuses.find((status) => status.provider === entry.id && status.configured)))
              .map((entry) => ({ value: String(entry.id), label: String(entry.name) })))]} onChange={value => setDraft({ ...draft,
            provider: value as ServiceProvider, key: "" })} disabled={busy} /></label>
          <p className={styles.providerIntro}>{selectedEntry.description}{t("。服务接口由系统内置。")}<a href={selectedEntry.keyUrl}
            target="_blank" rel="noopener noreferrer">{t("前往官网申请 API Key ↗")}</a></p>
          <label>API Key<input type="password" autoComplete="off" value={draft.key} minLength={8} maxLength={512} required
            placeholder={t("填写供应商 API Key")} onChange={(event) => setDraft({ ...draft, key: event.target.value })} /></label>
          <div className={styles.instanceActions}>
            <button type="submit" disabled={busy || draft.key.trim().length < 8}><Check />{t("保存")}</button>
            <button type="button" disabled={busy} onClick={() => setDraft(null)}>{t("取消")}</button>
          </div>
        </form>
      </div>
    </div>}
  </div>;
}

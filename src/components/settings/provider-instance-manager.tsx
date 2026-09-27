"use client";

import { Check, LoaderCircle, Plus, PlugZap, Settings2, Trash2 } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import type { BuiltinProvider, ProviderCapability, ProviderInstance, ProviderScope } from "@/lib/provider-instances";
import { normalizeProviderBaseUrl, PROVIDER_CATALOG } from "@/lib/provider-catalog";
import type { PlatformProviderCredential } from "@/lib/platform-provider-credentials";
import type { PipelineFallback } from "@/lib/provider-pipeline";
import { selectProviderInstanceForUse } from "@/lib/provider-selection-flow";
import { PROVIDER_SCOPE_DISPLAY_ORDER } from "./provider-scope-order";
import styles from "./provider-settings-screen.module.css";

const CAPABILITIES: { id: ProviderCapability; title: string }[] = [
  { id: "asr", title: "ASR · 语音识别" },
  { id: "tts", title: "TTS · 语音合成" },
  { id: "llm", title: "LLM · 对话模型" },
];

type Draft = { id?: string; scope: ProviderScope; capability: ProviderCapability; provider: BuiltinProvider;
  displayName: string; baseUrl: string; model: string; apiKey: string; enabled: boolean; expectedRevision?: string };

const statusLabel = (instance: ProviderInstance) => instance.connectionStatus === "passed"
  ? instance.capability === "llm" ? "流式测试通过" : "实时契约通过"
  : instance.connectionStatus === "failed" ? instance.capability === "llm" ? "流式测试未通过" : "实时测试未通过" : "未测试";
const PIPELINE: { id: ProviderCapability; label: string; detail: string }[] = [
  { id: "asr", label: "ASR · 听懂", detail: "语音 → 文字" },
  { id: "llm", label: "LLM · 思考", detail: "文字 → 回复" },
  { id: "tts", label: "TTS · 说话", detail: "回复 → 语音" },
];

export function ProviderInstanceManager({ admin }: { admin: boolean }) {
  const [instances, setInstances] = useState<ProviderInstance[]>([]);
  const [selections, setSelections] = useState<Partial<Record<ProviderCapability, string>>>({});
  const [platformSelections, setPlatformSelections] = useState<Partial<Record<ProviderCapability, string>>>({});
  const [platformCredentials, setPlatformCredentials] = useState<PlatformProviderCredential[]>([]);
  const [pipelineFallbacks, setPipelineFallbacks] = useState<Partial<Record<ProviderCapability, PipelineFallback>>>({});
  const [platformTestResults, setPlatformTestResults] = useState<Record<string, { ok: boolean; message: string }>>({});
  const [draft, setDraft] = useState<Draft | null>(null);
  const [draftTest, setDraftTest] = useState<{ signature: string; ok: boolean; message: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [signedIn, setSignedIn] = useState(false);
  const [signedOut, setSignedOut] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [feedback, setFeedback] = useState("");

  const refresh = useCallback(async () => {
    const response = await fetch("/api/provider-instances", { cache: "no-store" });
    const data = await response.json() as { instances?: ProviderInstance[];
      selections?: Partial<Record<ProviderCapability, string>>;
      platformSelections?: Partial<Record<ProviderCapability, string>>;
      platformCredentials?: PlatformProviderCredential[];
      pipelineFallbacks?: Partial<Record<ProviderCapability, PipelineFallback>>;
      signedIn?: boolean; error?: string };
    if (response.status === 401) { setSignedOut(true); return; }
    if (!response.ok || !data.instances) throw new Error(data.error || "无法读取供应商实例");
    setInstances(data.instances);
    setSelections(data.selections ?? {});
    setPlatformSelections(data.platformSelections ?? {});
    setPlatformCredentials(data.platformCredentials ?? []);
    setPipelineFallbacks(data.pipelineFallbacks ?? {});
    setSignedIn(Boolean(data.signedIn));
    setSignedOut(false);
    setError("");
  }, []);

  useEffect(() => {
    void refresh().catch((cause: unknown) => setError(cause instanceof Error ? cause.message : "读取失败"))
      .finally(() => setLoading(false));
  }, [refresh]);

  function startCreate(capability: ProviderCapability) {
    const provider = PROVIDER_CATALOG[capability][0].id;
    const preset = PROVIDER_CATALOG[capability].find((entry) => entry.id === provider)!;
    setDraft({ capability, provider, scope: signedIn ? "personal" : "platform", displayName: preset.name,
      baseUrl: platformCredentials.find((entry) => entry.capability === capability && entry.provider === provider)?.baseUrl ?? preset.baseUrl,
      model: "", apiKey: "", enabled: true });
    setDraftTest(null);
    setError(""); setFeedback("");
  }

  function changeDraftProvider(provider: BuiltinProvider) {
    if (!draft || draft.id) return;
    const preset = PROVIDER_CATALOG[draft.capability].find((entry) => entry.id === provider);
    if (!preset) return;
    setDraft({ ...draft, provider, displayName: preset.name,
      baseUrl: platformCredentials.find((entry) => entry.capability === draft.capability && entry.provider === provider)?.baseUrl ?? preset.baseUrl,
      model: "", apiKey: "" });
    setDraftTest(null);
  }

  function startEdit(instance: ProviderInstance) {
    setDraft({ id: instance.id, scope: instance.scope, capability: instance.capability,
      provider: instance.provider, displayName: instance.displayName, model: instance.model,
      baseUrl: instance.baseUrl,
      apiKey: "", enabled: instance.enabled, expectedRevision: instance.revision });
    setDraftTest(null);
    setError(""); setFeedback("");
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!draft || busy) return;
    setBusy(true); setError(""); setFeedback("");
    try {
      const response = await fetch(draft.id ? `/api/provider-instances/${draft.id}` : "/api/provider-instances", {
        method: draft.id ? "PATCH" : "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scope: draft.scope, capability: draft.capability, provider: draft.provider,
          displayName: draft.displayName, baseUrl: draft.baseUrl, model: draft.model, enabled: draft.enabled,
          ...(draft.expectedRevision ? { expectedRevision: draft.expectedRevision } : {}),
          ...(draft.apiKey ? { apiKey: draft.apiKey } : {}) }),
      });
      const data = await response.json() as { error?: string };
      if (!response.ok) throw new Error(data.error || "保存失败");
      setDraft(null); await refresh(); setFeedback("实例已保存。请先通过该能力的实时测试，再设为当前使用。");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "保存失败"); }
    finally { setBusy(false); }
  }

  async function testDraft() {
    if (!draft || !draft.apiKey || busy) return;
    const signature = JSON.stringify([draft.scope, draft.capability, draft.provider, draft.baseUrl, draft.model, draft.apiKey]);
    setBusy(true); setError(""); setDraftTest(null);
    try {
      const response = await fetch("/api/provider-instances/preview-test", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scope: draft.scope, capability: draft.capability, provider: draft.provider,
          displayName: draft.displayName, baseUrl: draft.baseUrl, model: draft.model, apiKey: draft.apiKey }),
      });
      const result = await response.json() as { ok?: boolean; message?: string; error?: string };
      setDraftTest({ signature, ok: response.ok && result.ok === true, message: result.message || result.error || "测试失败" });
    } catch { setDraftTest({ signature, ok: false, message: "测试服务暂不可用" }); }
    finally { setBusy(false); }
  }

  async function act(instance: ProviderInstance, action: "test" | "select" | "default" | "delete") {
    if (busy || (action === "delete" && !window.confirm(`删除「${instance.displayName}」？如果它正在使用，请先切换或清除选择；删除会结束使用该实例的会话。`))) return;
    setBusy(true); setError(""); setFeedback("");
    try {
      if (action === "select") {
        const result = await selectProviderInstanceForUse(instance.id, instance.connectionStatus);
        await refresh();
        setFeedback(instance.capability === "tts"
          ? "已设为默认 TTS；已有角色仍按各自的音色来源选择同供应商配置。"
          : result.tested ? "实时能力测试通过，已设为当前使用；新会话将采用这个实例。" : "已设为当前使用；新会话将采用这个实例。");
        return;
      }
      const url = `/api/provider-instances/${instance.id}`;
      const response = await fetch(action === "delete" ? `${url}?scope=${instance.scope}`
        : `${url}/${action === "default" ? "select?scope=platform" : action}`, {
        method: action === "delete" ? "DELETE" : "POST",
      });
      const data = await response.json() as { error?: string; message?: string; ok?: boolean };
      if (!response.ok) throw new Error(data.error || "操作失败");
      await refresh();
      if (action === "test" && !data.ok) throw new Error(data.message || "连接测试未通过");
      setFeedback(action === "test" ? data.message || "连接测试完成"
        : action === "default" ? "已设为平台默认，新会话将采用这个实例。" : "实例已删除。");
    } catch (cause) {
      if (action === "select") await refresh().catch(() => {});
      setError(cause instanceof Error ? cause.message : "操作失败");
    }
    finally { setBusy(false); }
  }

  async function testPlatform(credential: PlatformProviderCredential) {
    if (busy) return;
    setBusy(true); setError(""); setFeedback("");
    try {
      const response = await fetch("/api/provider-instances/platform-test", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ capability: credential.capability, provider: credential.provider }),
      });
      const result = await response.json() as { ok?: boolean; message?: string; error?: string };
      const status = { ok: response.ok && result.ok === true, message: result.message || result.error || "测试失败" };
      setPlatformTestResults((current) => ({ ...current, [`${credential.capability}:${credential.provider}`]: status }));
      setFeedback(`${credential.name}：${status.message}`);
    } catch { setError(`${credential.name}：测试服务暂不可用`); }
    finally { setBusy(false); }
  }

  async function selectPlatform(credential: PlatformProviderCredential) {
    if (busy || !signedIn) return;
    setBusy(true); setError(""); setFeedback("");
    try {
      const response = await fetch(`/api/provider-selections/${credential.capability}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: credential.provider }),
      });
      const data = await response.json() as { error?: string };
      if (!response.ok) throw new Error(data.error || "切换平台供应商失败");
      await refresh();
      setFeedback(credential.capability === "tts"
        ? `已将 ${credential.name} 设为默认 TTS；已有角色仍按音色来源选择配置。`
        : `已选择 ${credential.name}，新会话将使用平台 Key。`);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "切换平台供应商失败"); }
    finally { setBusy(false); }
  }

  function activeToken(capability: ProviderCapability): string | null {
    const explicit = selections[capability] ?? platformSelections[capability];
    if (explicit) return explicit;
    const fallback = pipelineFallbacks[capability];
    return fallback?.scope === "platform" && platformCredentials.some((item) => item.capability === capability && item.provider === fallback.provider)
      ? `env:${fallback.provider}` : null;
  }

  function pipelineValue(capability: ProviderCapability): PipelineFallback {
    const explicit = selections[capability] ?? platformSelections[capability];
    if (explicit?.startsWith("env:")) {
      const credential = platformCredentials.find((item) => item.capability === capability && item.provider === explicit.slice(4));
      return credential ? { scope: "platform", provider: credential.provider, name: credential.name, keySuffix: credential.keySuffix }
        : { scope: "none", provider: "", name: "已选平台配置不可用" };
    }
    if (explicit) {
      const instance = instances.find((item) => item.id === explicit && item.capability === capability);
      return instance ? { scope: instance.scope, provider: instance.provider, name: instance.displayName, keySuffix: instance.keySuffix }
        : { scope: "none", provider: "", name: "已选配置不可用" };
    }
    return pipelineFallbacks[capability] ?? { scope: "none", provider: "", name: "未配置" };
  }

  async function clearSelection(capability: ProviderCapability, scope: ProviderScope) {
    if (busy) return;
    setBusy(true); setError(""); setFeedback("");
    try {
      const response = await fetch(`/api/provider-selections/${capability}?scope=${scope}`, { method: "DELETE" });
      const data = await response.json() as { error?: string };
      if (!response.ok) throw new Error(data.error || "恢复默认失败");
      await refresh();
      setFeedback(scope === "platform" ? "平台默认已清除；新会话将使用旧版平台配置。"
        : "个人选择已清除；新会话将使用平台默认或旧版配置。");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "恢复默认失败"); }
    finally { setBusy(false); }
  }

  return <div className={styles.manager}>
    {signedOut && <p className={styles.authNotice}>登录后可以管理个人供应商实例。<Link href="/api/user/login?next=/settings/providers">登录</Link></p>}
    {error && <p className={styles.error} role="alert">{error}</p>}
    {feedback && <p className={styles.authNotice} role="status">{feedback}</p>}
    <section className={styles.pipeline} aria-label="当前语音交互链路">
      <div className={styles.pipelineHeading}><h2>默认语音交互链路</h2><span>新角色默认 / 未指定角色时使用 · ASR → LLM → TTS</span></div>
      <div className={styles.pipelineSteps}>{PIPELINE.map((step) => {
        const value = pipelineValue(step.id);
        return <div className={styles.pipelineStep} key={step.id} data-unconfigured={value.scope === "none"}>
          <div className={styles.pipelineStage}><strong>{step.label}</strong><small>{step.detail}</small></div>
          <div className={styles.pipelineBinding}><span>{loading ? "读取中…" : value.name}</span>
            {!loading && <small>{value.scope === "personal" ? "个人配置" : value.scope === "platform" ? "平台配置" : "未配置"}
              {value.keySuffix ? ` · Key ····${value.keySuffix}` : ""}</small>}</div>
        </div>;
      })}</div>
      <p>显示配置名称及个人／平台来源。TTS 是默认配置；已有角色按其音色来源使用同供应商配置。</p>
    </section>
    {CAPABILITIES.map((capability) => {
      const entries = instances.filter((instance) => instance.capability === capability.id);
      return <section className={styles.group} key={capability.id} aria-label={capability.title}>
        <div className={styles.instanceHeading}>
          <h2>{capability.title}</h2>
          <button className={styles.addProviderButton} type="button" disabled={busy || loading || signedOut}
            onClick={() => startCreate(capability.id)}><Plus aria-hidden="true" />新建供应商</button>
        </div>
        {selections[capability.id] && <div className={styles.selectionActions}>
          {selections[capability.id] && <button type="button" disabled={busy}
            onClick={() => void clearSelection(capability.id, "personal")}>恢复平台默认</button>}
        </div>}
        {loading ? <p className={styles.emptyInstances}>正在读取实例…</p> : <div className={styles.scopeGroups}>{PROVIDER_SCOPE_DISPLAY_ORDER.map((scope) => {
          const scoped = entries.filter((instance) => instance.scope === scope);
          const fallback = scope === "platform" ? platformCredentials.filter((item) => item.capability === capability.id) : [];
          return <div className={styles.scopeGroup} key={scope}>
            <div className={styles.scopeHeading}><h3>{scope === "personal" ? "我的配置" : "平台配置"}</h3><span>{scoped.length + fallback.length ? `${scoped.length + fallback.length} 项` : "未配置"}</span></div>
            {scoped.length + fallback.length === 0 ? <p className={styles.emptyInstances}>{scope === "platform" ? "暂无平台配置" : "暂无个人配置"}</p>
              : <div className={styles.instanceList}>{scoped.map((instance) => <article className={styles.instanceCard}
              data-selected={activeToken(capability.id) === instance.id}
              key={instance.id}>
            <div className={styles.instanceMeta}>
              <div className={styles.instanceIdentity}><h4>{instance.displayName}</h4><span>{instance.provider}</span><span>{instance.model ? `${instance.model} · ` : ""}Key ····{instance.keySuffix}</span></div>
              <div className={styles.instanceBadges}>
                {activeToken(capability.id) === instance.id &&
                  <span className={styles.state} data-configured="true">{capability.id === "tts" ? "默认使用" : "当前使用"}</span>}
                <span className={styles.state} data-test={instance.connectionStatus} title={instance.testMessage || undefined}>{instance.enabled ? statusLabel(instance) : "已停用"}</span>
              </div>
            </div>
            <div className={styles.instanceActions}>
              {signedIn && instance.enabled && <button type="button" disabled={busy || activeToken(capability.id) === instance.id}
                onClick={() => void act(instance, "select")}><Check />{instance.connectionStatus === "passed"
                  ? capability.id === "tts" ? "设为默认" : "设为当前"
                  : capability.id === "tts" ? "测试并设为默认" : "测试并设为当前"}</button>}
              <button type="button" disabled={busy} onClick={() => void act(instance, "test")}><PlugZap />测试</button>
              {instance.scope === "personal" && <>
                <button type="button" disabled={busy} onClick={() => startEdit(instance)}><Settings2 />编辑</button>
                <button type="button" disabled={busy} onClick={() => void act(instance, "delete")}><Trash2 />删除</button>
              </>}
            </div>
          </article>)}{fallback.map((item) => {
            const result = platformTestResults[`${item.capability}:${item.provider}`];
            return <article className={styles.instanceCard} data-selected={activeToken(capability.id) === `env:${item.provider}`}
              key={`env:${item.capability}:${item.provider}`}>
              <div className={styles.instanceMeta}>
                <div className={styles.instanceIdentity}><h4>{item.name}</h4><span>环境变量</span><span>Key ····{item.keySuffix}</span></div>
                <div className={styles.instanceBadges}>{activeToken(capability.id) === `env:${item.provider}` &&
                  <span className={styles.state} data-configured="true">{capability.id === "tts" ? "默认使用" : "当前使用"}</span>}<span className={styles.state} data-test={result ? result.ok ? "passed" : "failed" : "untested"}
                  title={result?.message}>{result ? result.ok ? "测试通过" : "测试未通过" : "未测试"}</span></div>
              </div>
              <div className={styles.instanceActions}>
                {signedIn && <button type="button" disabled={busy || activeToken(capability.id) === `env:${item.provider}`}
                  onClick={() => void selectPlatform(item)}><Check />{capability.id === "tts" ? "设为默认" : "设为当前"}</button>}
                <button type="button" disabled={busy} onClick={() => void testPlatform(item)}><PlugZap />测试</button>
              </div>
            </article>;
          })}</div>}
          </div>;
        })}</div>}
      </section>;
    })}
    <p className={styles.footnote}>未测试的个人配置会先运行实时能力测试，通过后才能选用；ASR 测试会使用平台豆包 TTS 生成固定音频，TTS 测试会发送两段固定文本，可能产生少量供应商用量。测试失败不会切换。角色音色与默认 TTS 来源不同时，会优先匹配同供应商已测试的配置。自定义 bridge 在隔离运行环境就绪前不会执行用户代码。</p>
    {draft && <div className={styles.instanceDialogBackdrop} role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setDraft(null); }}>
      <div className={styles.instanceDialog} role="dialog" aria-modal="true" aria-labelledby="provider-instance-title">
        <h2 id="provider-instance-title">{draft.id ? "编辑供应商" : `新建 ${draft.capability.toUpperCase()} 供应商`}</h2>
        <form onSubmit={(event) => void save(event)} className={styles.instanceForm}>
          {!draft.id && <label>供应商<select value={draft.provider} onChange={(event) => changeDraftProvider(event.target.value as BuiltinProvider)}>
            {PROVIDER_CATALOG[draft.capability].map((preset) => <option value={preset.id} key={preset.id}>{preset.name}</option>)}
          </select></label>}
          <p className={styles.providerIntro}>{PROVIDER_CATALOG[draft.capability].find((item) => item.id === draft.provider)?.intro} <a href={PROVIDER_CATALOG[draft.capability].find((item) => item.id === draft.provider)?.keyUrl} target="_blank" rel="noopener noreferrer">前往官网申请 API Key ↗</a>
            {draft.id ? " 修改配置会结束正在使用该实例的会话。" : ""}</p>
          {admin && !draft.id && <label>配置范围<select value={draft.scope} onChange={(event) => setDraft({ ...draft, scope: event.target.value as ProviderScope })}>
            {signedIn && <option value="personal">我的配置</option>}<option value="platform">平台配置</option></select></label>}
          <label>名称<input value={draft.displayName} maxLength={80} required onChange={(event) => setDraft({ ...draft, displayName: event.target.value })} /></label>
          <label>Base URL<input value={draft.baseUrl} type="url" required onChange={(event) => setDraft({ ...draft, baseUrl: event.target.value })} /></label>
          <p className={styles.urlHint}>内置 bridge 仅允许对应供应商的官方 HTTPS 地址。</p>
          {draft.capability === "llm" && <label>模型 ID<input value={draft.model} maxLength={100} placeholder="留空使用服务端默认模型"
            onChange={(event) => setDraft({ ...draft, model: event.target.value })} /></label>}
          <label>API Key<input value={draft.apiKey} type="password" autoComplete="off" minLength={draft.id ? undefined : 8}
            required={!draft.id} placeholder={draft.id ? "留空则保留现有 Key" : "填写供应商 API Key"}
            onChange={(event) => setDraft({ ...draft, apiKey: event.target.value })} /></label>
          {draft.id && <label className={styles.checkboxLabel}><input type="checkbox" checked={draft.enabled}
            onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })} />启用实例</label>}
          {draftTest?.signature === JSON.stringify([draft.scope, draft.capability, draft.provider, draft.baseUrl, draft.model, draft.apiKey]) &&
            <p className={draftTest.ok ? styles.testPassed : styles.testFailed} role="status">{draftTest.message}</p>}
          <div className={styles.instanceActions}>
            <button type="button" disabled={busy || draft.apiKey.length < 8 || !normalizeProviderBaseUrl(draft.capability, draft.provider, draft.baseUrl)}
              onClick={() => void testDraft()}><PlugZap />测试</button>
            <button type="submit" disabled={busy || !draft.displayName.trim() || !normalizeProviderBaseUrl(draft.capability, draft.provider, draft.baseUrl) || (!draft.id && draft.apiKey.length < 8)}>
              {busy ? <LoaderCircle className={styles.spin} /> : <Check />}保存</button>
            <button type="button" disabled={busy} onClick={() => setDraft(null)}>取消</button>
          </div>
        </form>
      </div>
    </div>}
  </div>;
}

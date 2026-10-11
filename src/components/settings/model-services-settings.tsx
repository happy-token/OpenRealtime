"use client";
import { LocalizedText } from "@/components/language/language-provider";

import { useLanguage } from "@/components/language/language-provider";


import { useEffect, useState } from "react";
import Link from "next/link";
import { Check, CircleHelp, LoaderCircle, PlugZap, Save, TestTube2 } from "lucide-react";
import styles from "./model-services-settings.module.css";

type Kind = "lipforcing" | "musetalk" | "wav2lip" | "liveportrait";
type ServiceView = { url: string; tokenConfigured: boolean };
type PlatformStatus = { configured: boolean; ready: boolean; message: string };
type ServiceDraft = ServiceView & { token: string; clearToken: boolean; busy: "save" | "test" | null; result: string; ready: boolean | null };

const SERVICES: Array<{ kind: Kind; name: string; purpose: string; hint: string }> = [
  { kind: "liveportrait", name: "LivePortrait", purpose: "形象动作", hint: "人像图与驱动动作生成视频" },
  { kind: "musetalk", name: "MuseTalk", purpose: "口型动作", hint: "基于动作底片和音频生成口型" },
  { kind: "wav2lip", name: "Wav2Lip", purpose: "口型动作", hint: "非商业用途的口型对齐" },
  { kind: "lipforcing", name: "Lip Forcing", purpose: "口型动作", hint: "GPU 口型生成服务" },
];
const PERSONAL_SERVICES = SERVICES.filter(({ kind }) => kind !== "liveportrait");

const EMPTY: ServiceDraft = { url: "", tokenConfigured: false, token: "", clearToken: false, busy: null, result: "", ready: null };
const initial = () => Object.fromEntries(SERVICES.map(({ kind }) => [kind, { ...EMPTY }])) as Record<Kind, ServiceDraft>;

export function ModelServicesSettings({ scope = "platform" }: { scope?: "personal" | "platform" }) {
  const { t } = useLanguage();
  const services = scope === "personal" ? PERSONAL_SERVICES : SERVICES;
  const endpoint = scope === "personal" ? "/api/user/model-services" : "/api/settings/model-services";
  const [drafts, setDrafts] = useState<Record<Kind, ServiceDraft>>(initial);
  const [loading, setLoading] = useState(true);
  const [needsAdmin, setNeedsAdmin] = useState(false);
  const [pageError, setPageError] = useState("");
  const [platformStatuses, setPlatformStatuses] = useState<Partial<Record<Kind, PlatformStatus>>>({});
  const [platformStatusLoading, setPlatformStatusLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    async function refreshStatus() {
      try {
        const response = await fetch("/api/services/model-status", { signal: controller.signal, cache: "no-store" });
        const body = await response.json() as { services?: Partial<Record<Kind, PlatformStatus>> };
        if (!response.ok || !body.services) throw new Error("状态检查失败");
        if (!controller.signal.aborted) setPlatformStatuses(body.services);
      } catch {
        if (!controller.signal.aborted) setPlatformStatuses({});
      } finally {
        if (!controller.signal.aborted) setPlatformStatusLoading(false);
      }
    }
    void refreshStatus();
    const timer = window.setInterval(() => void refreshStatus(), 30_000);
    window.addEventListener("focus", refreshStatus);
    return () => { controller.abort(); window.clearInterval(timer); window.removeEventListener("focus", refreshStatus); };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void fetch(endpoint, { signal: controller.signal, cache: "no-store" })
      .then(async (response) => {
        if (response.status === 401) { setNeedsAdmin(true); return; }
        const body = await response.json() as { services?: Record<Kind, ServiceView>; error?: string };
        if (!response.ok || !body.services) throw new Error(body.error || "读取服务配置失败");
        if (!controller.signal.aborted) setDrafts(Object.fromEntries(services.map(({ kind }) => [kind, {
          ...EMPTY, url: body.services?.[kind]?.url || "", tokenConfigured: Boolean(body.services?.[kind]?.tokenConfigured),
        }])) as Record<Kind, ServiceDraft>);
      })
      .catch((error) => { if (!controller.signal.aborted) setPageError(error instanceof Error ? error.message : "读取服务配置失败"); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [endpoint, services]);

  function update(kind: Kind, patch: Partial<ServiceDraft>) {
    setDrafts((current) => ({ ...current, [kind]: { ...current[kind], ...patch } }));
  }

  async function submit(kind: Kind, action: "save" | "test") {
    const draft = drafts[kind];
    update(kind, { busy: action, result: "", ready: null });
    try {
      const body = { kind, url: draft.url.trim(), ...(draft.token ? { token: draft.token } : draft.clearToken ? { token: "" } : {}) };
      const response = await fetch(action === "save" ? endpoint : `${endpoint}/test`, {
        method: action === "save" ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      const result = await response.json() as { error?: string; message?: string; ready?: boolean; url?: string; tokenConfigured?: boolean };
      if (!response.ok) throw new Error(result.error || "操作失败");
      update(kind, action === "save" ? {
        url: result.url || "", tokenConfigured: Boolean(result.tokenConfigured), token: "", clearToken: false,
        result: scope === "personal" ? "已保存，自己的口型生成任务将使用此服务。" : "已保存。生成时将优先使用此地址。", ready: null, busy: null,
      } : { result: result.message || "连接测试完成", ready: Boolean(result.ready), busy: null });
    } catch (error) {
      update(kind, { result: error instanceof Error ? error.message : "操作失败", ready: false, busy: null });
    }
  }

  if (loading) return <div className={styles.notice}><LoaderCircle className={styles.spin} />{t("正在读取服务配置…")}</div>;
  if (needsAdmin) return scope === "platform" ? null : <>
    <div className={styles.grid}>{SERVICES.map(({ kind, name }) => {
      const status = platformStatuses[kind];
      return <section className={styles.card} key={kind} aria-label={"" + (name) + t(" 平台服务状态")}>
        <div className={styles.heading}><h3>{name}</h3><span className={status?.ready ? styles.configured : styles.unconfigured}>{status ? status.ready ? t("已配置 · 已就绪") : status.configured ? t("连接异常") : t("未配置") : platformStatusLoading ? t("检测中") : t("状态暂不可用")}</span></div>
        <p role="status" className={styles.note}>{<LocalizedText text={status?.message ?? (platformStatusLoading ? "正在检查平台服务连接" : "状态检查失败，请稍后重试")} />}</p>
      </section>;
    })}</div>
    <div className={styles.notice}><CircleHelp />{t("登录后可配置个人模型服务。")}<Link href="/api/user/login?next=/settings/services">{t("登录")}</Link></div>
  </>;
  if (pageError) return <div className={styles.notice}>{pageError}</div>;

  return <div className={styles.layout}>
    <div className={styles.guide}>
      <PlugZap aria-hidden="true" />
      <div><strong>{scope === "personal" ? t("连接个人口型模型服务") : t("连接平台模型服务")}</strong><span>{scope === "personal" ? t("服务支持运营方允许的 HTTP(S) 地址，包括公网 IP 和端口；只有你自己的生成任务会使用这些配置。") : t("填写应用服务器能访问到的 URL，保存后生成任务将使用对应服务。")}{t("连接测试不会提交生成任务。")}</span></div>
    </div>
    <div className={styles.grid}>{services.map(({ kind, name, purpose, hint }) => {
      const draft = drafts[kind];
      const platform = platformStatuses[kind];
      return <section className={styles.card} key={kind} aria-label={"" + (name) + t(" 服务配置")}>
        <div className={styles.heading}><div><small>{purpose}</small><h3>{name}</h3><p>{<LocalizedText text={hint} />}</p></div><span className={draft.url ? styles.configured : styles.unconfigured}>{scope === "personal" ? t("个人") : ""}{draft.url ? t("已配置") : t("未配置")}</span></div>
        <p role="status" className={platform?.ready ? styles.result : styles.note}>{t("平台服务：")}{platform ? platform.ready ? t("已配置 · 连接正常，模型已就绪") : platform.configured ? t("已配置 · ") + (platform.message) + "" : t("未配置") : t("状态暂不可用")}</p>
        {scope === "personal" && <p className={styles.note}>{t("以下为个人配置；平台连接状态不代表已配置个人服务。")}</p>}
        <label className={styles.field}><span>{t("服务 URL")}</span><input type="url" inputMode="url" autoComplete="url" placeholder={scope === "personal" ? "https://models.example.com" : `http://127.0.0.1:${kind === "lipforcing" ? "8190" : kind === "musetalk" ? "18191" : kind === "wav2lip" ? "18192" : "18193"}`} value={draft.url} onChange={(event) => update(kind, { url: event.target.value, result: "", ready: null })} /></label>
        <details className={styles.advanced}><summary>{t("访问令牌（可选）")}{draft.tokenConfigured ? t(" · 已保存") : ""}</summary>
          <label className={styles.field}><span>{t("令牌只保存在服务器，不会在页面回显")}</span><input type="password" autoComplete="new-password" placeholder={draft.tokenConfigured ? t("留空保持现有令牌") : t("未启用令牌可留空")} value={draft.token} onChange={(event) => update(kind, { token: event.target.value, clearToken: false })} /></label>
          {draft.tokenConfigured && <label className={styles.clearToken}><input type="checkbox" checked={draft.clearToken} onChange={(event) => update(kind, { clearToken: event.target.checked, token: "" })} />{t("清除已保存的令牌")}</label>}
        </details>
        <div className={styles.footer}><div className={styles.actions}>
          <button type="button" className={styles.test} disabled={Boolean(draft.busy) || !draft.url.trim()} onClick={() => void submit(kind, "test")}>{draft.busy === "test" ? <LoaderCircle className={styles.spin} /> : <TestTube2 />}{t("测试连接")}</button>
          <button type="button" className={styles.save} disabled={Boolean(draft.busy)} onClick={() => void submit(kind, "save")}>{draft.busy === "save" ? <LoaderCircle className={styles.spin} /> : <Save />}{t("保存")}</button>
        </div>{draft.result && <p className={draft.ready === false ? styles.error : styles.result}>{draft.ready === true && <Check />}{draft.result}</p>}</div>
      </section>;
    })}</div>
    <p className={styles.note}>{scope === "personal" ? t("个人配置不会覆盖平台地址或其他用户的配置；未获允许运营方来源的服务无法保存。") : t("提示：这里填写的是模型服务地址，不是 Docker 容器内的地址。若应用也运行在容器中，请使用容器网络中可访问的服务名或代理地址。")}</p>
  </div>;
}

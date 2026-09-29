"use client";
import { useLanguage } from "@/components/language/language-provider";


import { useEffect, useState } from "react";
import Link from "next/link";
import { useCurrentUser, accountLoginHref } from "@/hooks/use-current-user";
import styles from "./model-services-settings.module.css";

type ServiceState = { configured: boolean; url: string; tokenConfigured: boolean };

export function PersonalLipsyncServiceSettings() {
  const { t } = useLanguage();
  const currentUser = useCurrentUser();
  const [service, setService] = useState<ServiceState>({ configured: false, url: "", tokenConfigured: false });
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (currentUser.status !== "signed-in") return;
    const controller = new AbortController();
    void fetch("/api/user/lipsync-service", { cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        const data = await response.json() as ServiceState & { error?: string };
        if (!response.ok) throw new Error(data.error || "读取失败");
        if (!controller.signal.aborted) { setService(data); setUrl(data.url); }
      }).catch((error) => { if (!controller.signal.aborted) setMessage(error instanceof Error ? error.message : "读取失败"); });
    return () => controller.abort();
  }, [currentUser.status]);

  async function act(method: "PUT" | "POST" | "DELETE") {
    setBusy(true); setMessage("");
    try {
      const response = await fetch("/api/user/lipsync-service", {
        method,
        headers: method === "PUT" ? { "Content-Type": "application/json" } : undefined,
        body: method === "PUT" ? JSON.stringify({ url: url.trim(), ...(token ? { token } : {}) }) : undefined,
      });
      const data = await response.json() as ServiceState & { error?: string; message?: string; ready?: boolean };
      if (!response.ok) throw new Error(data.error || "操作失败");
      if (method === "PUT") { setService(data); setToken(""); setMessage("已保存个人口型服务"); }
      if (method === "DELETE") { setService({ configured: false, url: "", tokenConfigured: false }); setUrl(""); setToken(""); setMessage("已删除个人口型服务"); }
      if (method === "POST") setMessage(data.message || (data.ready ? "连接正常" : "连接失败"));
    } catch (error) { setMessage(error instanceof Error ? error.message : "操作失败"); }
    finally { setBusy(false); }
  }

  if (currentUser.status !== "signed-in") return <div className={styles.notice}>{t("登录后可配置个人口型对齐服务。")}<Link href={accountLoginHref("/settings/services")}>{t("登录")}</Link></div>;
  return <section className={styles.card} aria-label={t("个人口型对齐服务")}>
    <div className={styles.heading}><div><small>{t("高级模式")}</small><h3>{t("个人口型对齐服务")}</h3><p>{t("仅用于你自己的口型生成任务；地址须由站点运营方列入允许来源。")}</p></div><span>{service.configured ? t("已配置") : t("未配置")}</span></div>
    <label className={styles.field}><span>{t("HTTPS 服务地址")}</span><input type="url" value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://lipsync.example.com" /></label>
    <label className={styles.field}><span>{t("访问令牌")}{service.tokenConfigured ? t("（已保存；留空保持）") : t("（可选）")}</span><input type="password" autoComplete="new-password" value={token} onChange={(event) => setToken(event.target.value)} /></label>
    <div className={styles.footer}><div className={styles.actions}>
      <button type="button" className={styles.save} disabled={busy || !url.trim()} onClick={() => void act("PUT")}>{t("保存")}</button>
      <button type="button" className={styles.test} disabled={busy || !service.configured} onClick={() => void act("POST")}>{t("测试连接")}</button>
      <button type="button" className={styles.test} disabled={busy || !service.configured} onClick={() => void act("DELETE")}>{t("删除")}</button>
    </div>{message && <p role="status" className={styles.result}>{message}</p>}</div>
  </section>;
}

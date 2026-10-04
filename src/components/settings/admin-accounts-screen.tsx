"use client";
import { useLanguage } from "@/components/language/language-provider";

import { useEffect, useState, type FormEvent } from "react";
import { ShieldCheck, Trash2 } from "lucide-react";
import { readJsonResponse } from "@/lib/http-json-response";
import type { AppAdminAccount } from "@/lib/app-admin-accounts";
import styles from "./admin-accounts-screen.module.css";

interface AdminAccountsResponse {
  admins: AppAdminAccount[];
}

export function AdminAccountsScreen() {
  const { t } = useLanguage();
  const [admins, setAdmins] = useState<AppAdminAccount[] | null>(null);
  const [subject, setSubject] = useState("");
  const [issuer, setIssuer] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setError("");
    void fetch("/api/admin-accounts", { cache: "no-store", signal: controller.signal }).then(async (response) => {
      const payload = await readJsonResponse<AdminAccountsResponse & { error?: string }>(response, "管理员列表读取失败");
      if (!response.ok) throw new Error(payload.error || "管理员列表读取失败");
      if (!controller.signal.aborted) setAdmins(payload.admins);
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "管理员列表读取失败");
    });
    return () => controller.abort();
  }, [refresh]);

  async function grant(event: FormEvent) {
    event.preventDefault();
    if (busy || !subject.trim()) return;
    setBusy(true);
    setError("");
    setStatus("");
    try {
      const response = await fetch("/api/admin-accounts", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ subject: subject.trim(), ...(issuer.trim() ? { issuer: issuer.trim() } : {}) }),
      });
      const payload = await readJsonResponse<AdminAccountsResponse & { error?: string }>(response, "设置管理员失败");
      if (!response.ok) throw new Error(payload.error || "设置管理员失败");
      setAdmins(payload.admins);
      setSubject("");
      setIssuer("");
      setStatus("已添加为管理员账号。");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "设置管理员失败"); }
    finally { setBusy(false); }
  }

  async function revoke(target: AppAdminAccount) {
    if (busy) return;
    setBusy(true);
    setError("");
    setStatus("");
    try {
      const response = await fetch("/api/admin-accounts", {
        method: "DELETE", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ subject: target.subject, issuer: target.issuer }),
      });
      const payload = await readJsonResponse<AdminAccountsResponse & { error?: string }>(response, "移除管理员失败");
      if (!response.ok) throw new Error(payload.error || "移除管理员失败");
      setAdmins(payload.admins);
      setStatus("已移除管理员账号。");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "移除管理员失败"); }
    finally { setBusy(false); }
  }

  return <div className={styles.page}>
    <h1><ShieldCheck aria-hidden="true" />{t("管理员账号")}</h1>
    <p className={styles.intro}>{t("管理员账号可以查看决策日志与打断延迟诊断，并管理这份管理员列表。")}</p>
    {error ? <p role="alert" className={styles.error}>{t(error)}<button onClick={() => setRefresh((value) => value + 1)}>{t("重试")}</button></p> : null}

    <section className={styles.section} aria-labelledby="admin-accounts-grant-title">
      <h2 id="admin-accounts-grant-title">{t("添加管理员")}</h2>
      <p className={styles.note}>{t("输入对方账号的 ID（对方可在「个人资料」页查看自己的账号 ID），添加后该账号即可访问诊断页面。")}</p>
      <form className={styles.grantForm} onSubmit={grant}>
        <label>{t("账号 ID")}<input value={subject} onChange={(event) => setSubject(event.target.value)} disabled={busy} placeholder={t("粘贴对方的账号 ID")} /></label>
        <label>{t("身份来源（可选）")}<input value={issuer} onChange={(event) => setIssuer(event.target.value)} disabled={busy} placeholder="issuer" /></label>
        <button type="submit" disabled={busy || !subject.trim()}>{t("添加为管理员")}</button>
      </form>
    </section>

    <section className={styles.section} aria-labelledby="admin-accounts-list-title">
      <h2 id="admin-accounts-list-title">{t("当前管理员")}</h2>
      {!admins && !error ? <p role="status">{t("正在读取管理员列表…")}</p> : null}
      <div className={styles.list}>
        {admins?.map((admin) => (
          <div className={styles.row} key={JSON.stringify([admin.issuer, admin.subject])}>
            <span><strong>{admin.subject}</strong><small>{admin.issuer}</small><small>{t("授予方")}: {admin.granted_by}</small></span>
            <button type="button" data-danger disabled={busy || (admins?.length ?? 0) <= 1} onClick={() => void revoke(admin)} aria-label={t("移除管理员 ") + admin.subject}><Trash2 /></button>
          </div>
        ))}
        {admins && !admins.length ? <p className={styles.note}>{t("当前没有管理员账号。")}</p> : null}
      </div>
    </section>
    <p role="status" aria-live="polite" className={styles.status}>{busy ? t("正在处理…") : t(status)}</p>
  </div>;
}

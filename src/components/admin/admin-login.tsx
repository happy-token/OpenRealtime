"use client";
import { useLanguage } from "@/components/language/language-provider";


import { BackLink } from "@/components/workspace/back-link";

import { useState, type FormEvent } from "react";
import { LockKeyhole, RadioTower } from "lucide-react";
import styles from "@/app/admin/admin.module.css";
import type { AdminLoginDefaults } from "@/lib/admin-auth";

interface AdminLoginProps {
  configured: boolean;
  defaultCredentials: AdminLoginDefaults | null;
}

export function AdminLogin({ configured, defaultCredentials }: AdminLoginProps) {
  const { t } = useLanguage();
  const [username, setUsername] = useState(defaultCredentials?.username ?? "");
  const [password, setPassword] = useState(defaultCredentials?.password ?? "");
  const [error, setError] = useState(configured ? "" : "请先在环境变量中配置管理员账户");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!configured || loading) return;
    setLoading(true);
    setError("");
    try {
      const response = await fetch("/api/admin/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      const payload = await response.json() as { error?: string };
      if (!response.ok) throw new Error(payload.error ?? "登录失败");
      window.location.reload();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "登录失败");
      setLoading(false);
    }
  }

  return (
    <main className={`${styles.shell} ${styles.loginShell}`}>
      <form className={styles.loginCard} onSubmit={submit}>
        <span className={styles.loginIcon}><RadioTower aria-hidden="true" /></span>

        <h1>{t("运行诊断中心")}</h1>
        <p className={styles.loginIntro}>{t("仅管理员可查看会话链路、性能指标和错误日志。")}</p>
        <label>{t("管理员账户")}<input autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} disabled={!configured} /></label>
        <label>{t("密码")}<input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} disabled={!configured} /></label>
        {error ? <p className={styles.formError} role="alert">{t(error)}</p> : null}
        <button type="submit" disabled={!configured || loading}>
          <LockKeyhole aria-hidden="true" />{loading ? t("正在验证…") : t("安全登录")}
        </button>
        <BackLink href="/" label={t("返回语音主页")} />
      </form>
    </main>
  );
}

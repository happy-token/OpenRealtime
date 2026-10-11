"use client";

import { useLanguage } from "@/components/language/language-provider";


import { useCallback, useEffect, useState, type FormEvent } from "react";
import { KeyRound, LoaderCircle, LockKeyhole, Trash2 } from "lucide-react";
import type { PersonalKeyProvider } from "@/lib/user-provider-credentials";
import styles from "./user-key-settings.module.css";

interface KeyStatus {
  provider: PersonalKeyProvider;
  configured: boolean;
  platformConfigured: boolean;
  suffix?: string;
}

const PROVIDERS: { id: PersonalKeyProvider; label: string; purpose: string }[] = [
  { id: "anam", label: "Anam", purpose: "实时数字人" },
  { id: "doubao", label: "豆包语音", purpose: "语音识别 / 语音合成" },
  { id: "dashscope", label: "百炼语音", purpose: "可选的语音合成" },
  { id: "deepseek", label: "DeepSeek", purpose: "对话模型" },
  { id: "minimax", label: "MiniMax", purpose: "视频生成" },
];

export function UserKeySettings() {
  const { t } = useLanguage();
  const [statuses, setStatuses] = useState<KeyStatus[]>([]);
  const [active, setActive] = useState<PersonalKeyProvider | null>(null);
  const [value, setValue] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    const response = await fetch("/api/user/provider-keys", { cache: "no-store" });
    const payload = await response.json() as { credentials?: KeyStatus[]; error?: string };
    if (!response.ok || !payload.credentials) throw new Error(payload.error || "无法读取 API Key 状态");
    setStatuses(payload.credentials);
  }, []);

  useEffect(() => {
    void refresh().catch((cause: unknown) => {
      setError(cause instanceof Error ? cause.message : "无法读取 API Key 状态");
    }).finally(() => setLoading(false));
  }, [refresh]);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!active || saving || !value.trim()) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const response = await fetch("/api/user/provider-keys", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: active, apiKey: value.trim() }),
      });
      const payload = await response.json() as { error?: string };
      if (!response.ok) throw new Error(payload.error || "保存失败");
      setValue("");
      setActive(null);
      await refresh();
      setMessage("API Key 已保存，仅用于你本人发起的请求。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function remove(provider: PersonalKeyProvider) {
    const consequence = provider === "minimax"
      ? "清空后无法继续查询使用旧 Key 创建的 MiniMax 视频任务。"
      : "清空后相应的实时能力将使用平台 Key（如已配置）。";
    if (saving || !window.confirm(`清空这项 API Key？${consequence}`)) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const response = await fetch(`/api/user/provider-keys?provider=${provider}`, { method: "DELETE" });
      const payload = await response.json() as { error?: string };
      if (!response.ok) throw new Error(payload.error || "清空失败");
      await refresh();
      setMessage("已清空个人 API Key。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "清空失败");
    } finally {
      setSaving(false);
    }
  }

  return <div className={styles.page}>
    <div className={styles.shell}>
      <div className={styles.heading}>
        <span className={styles.headingIcon}><KeyRound size={23} /></span>
        <div><p className={styles.eyebrow}>{t("账户设置")}</p><h1>API Key</h1></div>
      </div>
      <p className={styles.intro}>{t("你保存的 Key 仅用于你本人发起的请求，不会提供给其他访客。保存后只显示末尾几位，可随时更换或清空。")}</p>
      <p className={styles.notice}>{t("未填写个人 Key 的实时服务会使用网站提供的 Key。平台语音识别和语音合成有并发及单次体验时长限制。动作服务页支持使用个人 MiniMax Key 生成视频；其他付费创作逐项验收后开放。个人 Key 无效或额度不足时会提示你处理，不会自动改用平台 Key。")}</p>
      {error && <p className={styles.error} role="alert">{t(error)}</p>}
      {message && <p className={styles.success} role="status">{message}</p>}
      <section className={styles.list} aria-label={t("服务商 API Key")}>
        {loading ? <p className={styles.loading}><LoaderCircle size={18} className={styles.spin} /> {t(" 正在读取配置")}</p>
          : PROVIDERS.map(({ id, label, purpose }) => {
            const status = statuses.find((item) => item.provider === id);
            return <article key={id} className={styles.card}>
              <div className={styles.cardHead}>
                <div><h2>{t(label)}</h2><p>{purpose}</p></div>
                <span className={status?.configured ? styles.personalBadge : styles.platformBadge}>
                  {status?.configured ? t("我的 Key") : id !== "minimax" && status?.platformConfigured ? t("平台 Key") : t("未配置")}
                </span>
              </div>
              <p className={styles.status}>{status?.configured
                ? <>{t("已保存 ····")}{status.suffix}</>
                : id === "minimax" ? t("保存个人 Key 后可在动作服务页生成视频")
                  : status?.platformConfigured ? t("已配置平台 Key；实时会话未设置个人 Key 时使用") : t("当前没有可用的 Key")}</p>
              {active === id ? <form className={styles.form} onSubmit={(event) => void save(event)}>
                <label htmlFor={`key-${id}`}>{t("填写 ")}{t(label)} API Key</label>
                <input id={`key-${id}`} type="password" autoComplete="off" value={value}
                  onChange={(event) => setValue(event.target.value)} placeholder={t("粘贴你的 API Key")} autoFocus />
                <div className={styles.actions}>
                  <button type="submit" disabled={saving || !value.trim()}>{saving ? t("正在保存") : t("保存 Key")}</button>
                  <button type="button" className={styles.secondary} disabled={saving}
                    onClick={() => { setActive(null); setValue(""); }}>{t("取消")}</button>
                </div>
              </form> : <div className={styles.actions}>
                <button type="button" disabled={saving} onClick={() => { setActive(id); setValue(""); }}>
                  {status?.configured ? t("更换 Key") : t("填写我的 Key")}
                </button>
                {status?.configured && <button type="button" className={styles.remove} disabled={saving}
                  onClick={() => void remove(id)}><Trash2 size={15} /> {t(" 清空")}</button>}
              </div>}
            </article>;
          })}
      </section>
      <p className={styles.footnote}><LockKeyhole size={15} /> {t(" Key 在服务端加密保存。完整内容不会再次显示，也不会写入浏览器本地存储。")}</p>
      <button className={styles.logout} type="button" onClick={() => void fetch("/api/user/logout", { method: "POST" })
        .then((response) => { if (!response.ok) throw new Error("退出登录失败"); window.location.href = "/"; })
        .catch((cause: unknown) => setError(cause instanceof Error ? cause.message : "退出登录失败"))}>{t("退出登录")}</button>
    </div>
  </div>;
}

"use client";
import { useLanguage } from "@/components/language/language-provider";


import { LanguageSelect } from "@/components/language/language-select";
import Link from "next/link";
import { KeyRound, LogIn, MemoryStick, Palette, PlugZap, Settings2, UserRound } from "lucide-react";
import { accountIssuerLabel, accountLoginHref, useCurrentUser } from "@/hooks/use-current-user";
import styles from "./account-settings-screen.module.css";

function ProfileCard() {
  const { t } = useLanguage();
  const currentUser = useCurrentUser();
  if (currentUser.status === "signed-in") return <div className={styles.profile}>
    <span><UserRound /></span><div><strong>{currentUser.user.subject}</strong><small>{accountIssuerLabel(currentUser.user.issuer)}</small></div><Link href="/settings/providers">{t("账户设置")}</Link>
  </div>;
  return <div className={styles.profile}>
    <span>{currentUser.status === "loading" ? <UserRound /> : <LogIn />}</span>
    <div><strong>{currentUser.status === "loading" ? t("正在检查账户") : t("尚未登录")}</strong><small>{currentUser.status === "unavailable" ? t("账户服务暂时不可用") : t("登录后同步个人角色、凭证与记忆")}</small></div>
    <Link href={accountLoginHref("/settings/profile")}>{t("登录账户")}</Link>
  </div>;
}

export function AccountSettingsScreen({ section }: { section: "profile" | "settings" }) {
  const { t } = useLanguage();
  const settings = section === "settings";
  const title = settings ? "设置" : "个人资料";
  return <div className={styles.page}>
    <h1 className={styles.pageTitle}>{t(title)}</h1>
    <p className={styles.intro}>{settings ? t("管理供应商、模型服务、外观、Memory 与对话偏好。") : t("管理当前用户信息与账户入口。")}</p>
    {settings ? <><div className={styles.languageRow}><LanguageSelect /></div><div className={styles.rows}>
      <Link href="/settings/providers"><KeyRound /><span><strong>{t("供应商")}</strong><small>{t("管理 ASR、TTS 与 LLM 配置")}</small></span></Link>
      <Link href="/settings/services"><PlugZap /><span><strong>{t("模型服务")}</strong><small>{t("配置动作生成和口型对齐服务")}</small></span></Link>
      <Link href="/settings/appearance"><Palette /><span><strong>{t("外观")}</strong><small>{t("Orb、界面主题、动态和工作台玻璃效果")}</small></span></Link>
      <Link href="/settings/memory"><MemoryStick /><span><strong>{t("Memory 与隐私")}</strong><small>{t("查看角色记忆配置与数据边界")}</small></span></Link>
      <Link href="/settings/advanced"><Settings2 /><span><strong>{t("高级配置")}</strong><small>{t("对话设备与运行参数")}</small></span></Link>
      <Link href="/settings/profile"><UserRound /><span><strong>{t("个人资料")}</strong><small>{t("查看当前账户信息")}</small></span></Link>
    </div></> : <ProfileCard />}
  </div>;
}

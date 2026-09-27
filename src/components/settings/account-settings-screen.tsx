"use client";

import Link from "next/link";
import { KeyRound, LogIn, MemoryStick, Palette, PlugZap, Settings2, UserRound } from "lucide-react";
import { accountIssuerLabel, accountLoginHref, useCurrentUser } from "@/hooks/use-current-user";
import styles from "./account-settings-screen.module.css";

function ProfileCard() {
  const currentUser = useCurrentUser();
  if (currentUser.status === "signed-in") return <div className={styles.profile}>
    <span><UserRound /></span><div><strong>{currentUser.user.subject}</strong><small>{accountIssuerLabel(currentUser.user.issuer)}</small></div><Link href="/settings/providers">账户设置</Link>
  </div>;
  return <div className={styles.profile}>
    <span>{currentUser.status === "loading" ? <UserRound /> : <LogIn />}</span>
    <div><strong>{currentUser.status === "loading" ? "正在检查账户" : "尚未登录"}</strong><small>{currentUser.status === "unavailable" ? "账户服务暂时不可用" : "登录后同步个人角色、凭证与记忆"}</small></div>
    <Link href={accountLoginHref("/settings/profile")}>登录账户</Link>
  </div>;
}

export function AccountSettingsScreen({ section }: { section: "profile" | "settings" }) {
  const settings = section === "settings";
  const title = settings ? "设置" : "个人资料";
  return <div className={styles.page}>
    <h1 className={styles.pageTitle}>{title}</h1>
    <p className={styles.intro}>{settings ? "管理供应商、模型服务、外观、Memory 与对话偏好。" : "管理当前用户信息与账户入口。"}</p>
    {settings ? <div className={styles.rows}>
      <Link href="/settings/providers"><KeyRound /><span><strong>供应商</strong><small>管理 ASR、TTS 与 LLM 配置</small></span></Link>
      <Link href="/settings/services"><PlugZap /><span><strong>模型服务</strong><small>配置动作生成和口型对齐服务</small></span></Link>
      <Link href="/settings/appearance"><Palette /><span><strong>外观</strong><small>Orb、界面主题、动态和工作台玻璃效果</small></span></Link>
      <Link href="/settings/memory"><MemoryStick /><span><strong>Memory 与隐私</strong><small>查看角色记忆配置与数据边界</small></span></Link>
      <Link href="/settings/advanced"><Settings2 /><span><strong>高级配置</strong><small>对话设备与运行参数</small></span></Link>
      <Link href="/settings/profile"><UserRound /><span><strong>个人资料</strong><small>查看当前账户信息</small></span></Link>
    </div> : <ProfileCard />}
  </div>;
}

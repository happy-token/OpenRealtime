"use client";

import { ProviderCredentialManager } from "./provider-credential-manager";
import styles from "./provider-settings-screen.module.css";

export function ProviderSettingsScreen() {
  return <div className={styles.page}>
    <h1 className={styles.pageTitle}>供应商</h1>
    <p className={styles.intro}>管理语音与 LLM 服务的连接。凭证仅用于你的请求，完整内容不会再次显示。</p>
    <ProviderCredentialManager />
  </div>;
}

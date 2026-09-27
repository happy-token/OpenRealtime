"use client";

import { ProviderInstanceManager } from "./provider-instance-manager";
import { AdvancedServiceManager } from "./advanced-service-manager";
import styles from "./provider-settings-screen.module.css";

export function ProviderSettingsScreen({ showPlatformModelServices = false }: { showPlatformModelServices?: boolean }) {
  return <div className={styles.page}>
    <h1 className={styles.pageTitle}>供应商</h1>
    <p className={styles.intro}>按能力管理供应商配置。语音链路可选择当前实例，高级服务按各自能力接入。</p>
    <ProviderInstanceManager admin={showPlatformModelServices} />
    <details className={styles.advancedServices}>
      <summary><span>高级服务</span><small>Anam 实时数字人 · MiniMax 视频生成</small></summary>
      <AdvancedServiceManager />
    </details>
  </div>;
}

"use client";
import { useLanguage } from "@/components/language/language-provider";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";
import styles from "./loading.module.css";

export default function Loading() {
  const { t } = useLanguage();
  return <WorkspaceShell>
    <div className={styles.loadingContent} role="status" aria-label={t("正在切换页面")}>
      <span className={styles.indicator} aria-hidden="true" />
    </div>
  </WorkspaceShell>;
}

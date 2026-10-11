"use client";
import { useLanguage } from "@/components/language/language-provider";
import styles from "@/app/loading.module.css";

export function RouteLoading() {
  const { t } = useLanguage();
  return <div className={styles.loading} role="status" aria-label={t("正在切换页面")}>
    <span className={styles.indicator} aria-hidden="true" />
  </div>;
}

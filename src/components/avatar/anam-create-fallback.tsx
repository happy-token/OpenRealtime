"use client";

import { useLanguage } from "@/components/language/language-provider";
import styles from "./anam-create-fallback.module.css";

export function AnamCreateFallback() {
  const { t } = useLanguage();
  return <div className={styles.notice}>
    <p>{t("本地 API 创建失败不代表官网也会失败。可以在 Anam 官网使用个人 API Key 所属账号／组织上传原始图片并创建形象，再返回实时数字人形象库刷新并选择已有形象，无需重复创建。")}</p>
    <a href="https://lab.anam.ai" target="_blank" rel="noopener noreferrer">{t("前往 Anam 官网创建形象 ↗")}</a>
  </div>;
}

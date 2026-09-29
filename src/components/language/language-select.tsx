"use client";

import { SelectMenu } from "@/components/ui/select-menu";
import { Languages } from "lucide-react";
import { useLanguage } from "./language-provider";
import type { LanguagePreference } from "@/lib/app-language";
import styles from "./language-select.module.css";

export function LanguageSelect({ compact = false }: { compact?: boolean }) {
  const { preference, setPreference, t } = useLanguage();
  return <div className={styles.control} data-compact={compact} title={t("界面语言")}>
    {!compact && <span>{t("语言")}</span>}
    <SelectMenu<LanguagePreference>
      value={preference}
      ariaLabel={t("界面语言")}
      triggerRole="combobox"
      fullWidth
      triggerContent={compact ? <Languages size={19} aria-hidden="true" /> : undefined}
      options={[{ value: "system", label: t("跟随系统") }, { value: "zh-CN", label: "简体中文" }, { value: "en", label: "English" }]}
      onChange={setPreference}
    />
  </div>;
}

"use client";
import { useLanguage } from "@/components/language/language-provider";
import { CircleHelp } from "lucide-react";

interface InfoHintProps {
  text: string;
}

export function InfoHint({ text }: InfoHintProps) {
  const { t } = useLanguage();
  return (
    <span className="inline-info-hint" tabIndex={0} aria-label={t("帮助：{p0}", { p0: String(t(String(text))) })} data-tooltip={t(text)}>
      <CircleHelp aria-hidden="true" />
    </span>
  );
}

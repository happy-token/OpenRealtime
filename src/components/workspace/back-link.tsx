
import { LocalizedText } from "@/components/language/language-provider";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import type { ComponentProps } from "react";
import styles from "./back-link.module.css";

export function BackLink({ label, className, ...props }: Omit<ComponentProps<typeof Link>, "children"> & { label: string }) {
  return <Link {...props} className={[className, styles.button].filter(Boolean).join(" ")} aria-label={label} title={label}>
    <ArrowLeft aria-hidden="true" /><span>{<LocalizedText text={"返回"} />}</span>
  </Link>;
}

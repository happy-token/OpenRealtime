"use client";
import { LocalizedText } from "@/components/language/language-provider";

import { useLanguage } from "@/components/language/language-provider";


import Image from "next/image";
import { Check } from "lucide-react";
import type { OwnedAvatarRecord } from "@/lib/avatar-records";
import { AssetCard, type AssetTarget } from "./role-asset-management";
import styles from "./identity-choice-grid.module.css";

export function AvatarChoiceGrid({
  avatars,
  value,
  onChange,
  onManage,
  busy = false,
}: {
  avatars: readonly OwnedAvatarRecord[];
  value: string | null;
  onChange: (avatarId: string) => void;
  onManage?: (target: AssetTarget, operation: "rename" | "trash" | "restore" | "image") => void;
  busy?: boolean;
}) {
  const { t } = useLanguage();
  return <div className={styles.avatarGrid} role="group" aria-label={t("选择数字人形象")}>
    {avatars.filter(avatar => !avatar.deleted_at).map((avatar) => {
      const actionCount = avatar.actions.filter((asset) => !asset.deleted_at && asset.video_url).length;
      const card = <button className={styles.avatarCard} key={avatar.avatar_id} type="button" aria-pressed={value === avatar.avatar_id} data-selected={value === avatar.avatar_id} onClick={() => onChange(avatar.avatar_id)}>
        <span className={styles.avatarMedia}><Image src={avatar.source_image_url} alt="" fill sizes="(max-width: 560px) 50vw, 160px" unoptimized /></span>
        <span className={styles.avatarCopy}><strong>{<LocalizedText text={avatar.display_name} />}</strong><small>{actionCount}{t(" 个动作")}</small></span>
        {value === avatar.avatar_id ? <Check className={styles.check} aria-hidden="true" /> : null}
      </button>;
      return onManage ? <AssetCard key={avatar.avatar_id} target={{ avatar }} onManage={onManage} busy={busy}>{card}</AssetCard> : card;
    })}
  </div>;
}

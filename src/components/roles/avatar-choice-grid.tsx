"use client";

import Image from "next/image";
import { Check } from "lucide-react";
import type { OwnedAvatarRecord } from "@/lib/avatar-records";
import styles from "./identity-choice-grid.module.css";

export function AvatarChoiceGrid({
  avatars,
  value,
  onChange,
}: {
  avatars: readonly OwnedAvatarRecord[];
  value: string | null;
  onChange: (avatarId: string) => void;
}) {
  return <div className={styles.avatarGrid} role="group" aria-label="选择数字人形象">
    {avatars.map((avatar) => {
      const actionCount = avatar.actions.filter((asset) => !asset.deleted_at && asset.video_url).length;
      return <button className={styles.avatarCard} key={avatar.avatar_id} type="button" aria-pressed={value === avatar.avatar_id} data-selected={value === avatar.avatar_id} onClick={() => onChange(avatar.avatar_id)}>
        <span className={styles.avatarMedia}><Image src={avatar.source_image_url} alt="" fill sizes="(max-width: 560px) 50vw, 160px" unoptimized /></span>
        <span className={styles.avatarCopy}><strong>{avatar.display_name}</strong><small>{actionCount} 个动作</small></span>
        {value === avatar.avatar_id ? <Check className={styles.check} aria-hidden="true" /> : null}
      </button>;
    })}
  </div>;
}

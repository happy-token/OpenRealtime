"use client";
import { LocalizedText } from "@/components/language/language-provider";

import { useLanguage } from "@/components/language/language-provider";


import { BackLink } from "@/components/workspace/back-link";

import Image from "next/image";
import { Film, RotateCcw, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import {
  fetchOwnedAvatars,
  setOwnedAvatarDeletion,
  updateOwnedAvatarAction,
} from "@/lib/avatar-catalog-client";
import type { OwnedAvatarRecord } from "@/lib/avatar-records";
import styles from "./avatar-trash-screen.module.css";

export function AvatarTrashScreen({ returnHref = "/resources?tab=avatars" }: { returnHref?: string }) {
  const { t } = useLanguage();
  const [avatars, setAvatars] = useState<OwnedAvatarRecord[]>([]);
  const refresh = async () => setAvatars(await fetchOwnedAvatars());
  useEffect(() => {
    void refresh();
  }, []);
  const deletedAvatars = avatars.filter((avatar) => avatar.deleted_at);
  const deletedActions = avatars.flatMap((avatar) => avatar.actions.filter((action) => action.deleted_at).map((action) => ({ avatar, action })));

  return (
    <section className={styles.trash} aria-labelledby="avatar-trash-title">
      <header><h1 id="avatar-trash-title">{t("回收站")}</h1><span>{t("删除内容保留 30 天，期间可恢复。")}</span></header>
      {!deletedAvatars.length && !deletedActions.length ? (
        <div className={styles.empty}><Trash2 /><strong>{t("回收站是空的")}</strong><BackLink href={returnHref} label={t("返回资产管理")} /></div>
      ) : (
        <div className={styles.sections}>
          {deletedAvatars.length ? <section><h2>{t("数字人")}</h2><div className={styles.grid}>{deletedAvatars.map((avatar) => (
            <article key={avatar.avatar_id}>
              <div className={styles.image}><Image src={avatar.source_image_url} alt="" fill sizes="180px" unoptimized /></div>
              <div><strong>{<LocalizedText text={avatar.display_name} />}</strong><span>{remainingDays(avatar.deleted_at)}{t(" 天后清理")}</span></div>
              <button type="button" onClick={() => void setOwnedAvatarDeletion(avatar.avatar_id, false).then(refresh)}><RotateCcw />{t("恢复")}</button>
            </article>
          ))}</div></section> : null}
          {deletedActions.length ? <section><h2>{t("动作")}</h2><div className={styles.grid}>{deletedActions.map(({ avatar, action }) => (
            <article key={action.avatar_action_id}>
              <div className={styles.actionIcon}><Film /></div>
              <div><strong>{<LocalizedText text={action.display_name} />}</strong><small>{<LocalizedText text={avatar.display_name} />}</small><span>{remainingDays(action.deleted_at)}{t(" 天后清理")}</span></div>
              <button type="button" onClick={() => void updateOwnedAvatarAction(avatar.avatar_id, action.avatar_action_id, { operation: "restore" }).then(refresh)}><RotateCcw />{t("恢复")}</button>
            </article>
          ))}</div></section> : null}
        </div>
      )}
    </section>
  );
}

function remainingDays(deletedAt: string | null) {
  if (!deletedAt) return 30;
  const expiresAt = new Date(deletedAt).valueOf() + 30 * 24 * 60 * 60 * 1_000;
  return Math.max(0, Math.ceil((expiresAt - Date.now()) / (24 * 60 * 60 * 1_000)));
}

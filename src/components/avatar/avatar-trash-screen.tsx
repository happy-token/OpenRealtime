"use client";

import Image from "next/image";
import Link from "next/link";
import { Film, RotateCcw, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import {
  fetchOwnedAvatars,
  setOwnedAvatarDeletion,
  updateOwnedAvatarAction,
} from "@/lib/avatar-catalog-client";
import type { OwnedAvatarRecord } from "@/lib/avatar-records";
import styles from "./avatar-trash-screen.module.css";

export function AvatarTrashScreen() {
  const [avatars, setAvatars] = useState<OwnedAvatarRecord[]>([]);
  const refresh = async () => setAvatars(await fetchOwnedAvatars());
  useEffect(() => {
    void refresh();
  }, []);
  const deletedAvatars = avatars.filter((avatar) => avatar.deleted_at);
  const deletedActions = avatars.flatMap((avatar) => avatar.actions.filter((action) => action.deleted_at).map((action) => ({ avatar, action })));

  return (
    <section className={styles.trash} aria-labelledby="avatar-trash-title">
      <header><h1 id="avatar-trash-title">回收站</h1><span>删除内容保留 30 天，期间可恢复。</span></header>
      {!deletedAvatars.length && !deletedActions.length ? (
        <div className={styles.empty}><Trash2 /><strong>回收站是空的</strong><Link href="/avatars">返回资产管理</Link></div>
      ) : (
        <div className={styles.sections}>
          {deletedAvatars.length ? <section><h2>数字人</h2><div className={styles.grid}>{deletedAvatars.map((avatar) => (
            <article key={avatar.avatar_id}>
              <div className={styles.image}><Image src={avatar.source_image_url} alt="" fill sizes="180px" unoptimized /></div>
              <div><strong>{avatar.display_name}</strong><span>{remainingDays(avatar.deleted_at)} 天后清理</span></div>
              <button type="button" onClick={() => void setOwnedAvatarDeletion(avatar.avatar_id, false).then(refresh)}><RotateCcw />恢复</button>
            </article>
          ))}</div></section> : null}
          {deletedActions.length ? <section><h2>动作</h2><div className={styles.grid}>{deletedActions.map(({ avatar, action }) => (
            <article key={action.avatar_action_id}>
              <div className={styles.actionIcon}><Film /></div>
              <div><strong>{action.display_name}</strong><small>{avatar.display_name}</small><span>{remainingDays(action.deleted_at)} 天后清理</span></div>
              <button type="button" onClick={() => void updateOwnedAvatarAction(avatar.avatar_id, action.avatar_action_id, { operation: "restore" }).then(refresh)}><RotateCcw />恢复</button>
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

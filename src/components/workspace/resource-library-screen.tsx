"use client";
import { LocalizedText } from "@/components/language/language-provider";

import { useLanguage } from "@/components/language/language-provider";


import { BackLink } from "@/components/workspace/back-link";

import Link from "next/link";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Plus } from "lucide-react";
import { AvatarResourceHome } from "@/components/avatar/avatar-resource-home";
import { AvatarUploadDialog } from "@/components/avatar/avatar-upload-dialog";
import { PersonaLibraryScreen } from "@/components/persona/persona-library-screen";
import { ToolLibraryScreen } from "@/components/tools/tool-library-screen";
import { MemorySettingsScreen } from "@/components/settings/memory-settings-screen";
import { KnowledgeLibraryScreen } from "./knowledge-library-screen";
import { VoiceLibrary } from "./voice-library";
import { useOfficialRealtimeAvatars } from "@/hooks/use-official-realtime-avatars";
import type { AvatarWorkbenchTask } from "@/lib/avatar-workbench-navigation";
import styles from "./resource-library-screen.module.css";

export type ResourceTab = "voices" | "personas" | "tools" | "knowledge" | "memory" | "avatars" | "official-realtime";

export function ResourceLibraryScreen({
  tab,
  avatarTask,
  initialAvatarId,
  initialActionId,
  initialTalkingMethod,
  returnToRoleCreate = false,
  returnToRoleId,
  knowledgeRoleId,
}: {
  tab: ResourceTab;
  avatarTask?: AvatarWorkbenchTask;
  initialAvatarId?: string;
  initialActionId?: string;
  initialTalkingMethod?: "lipforcing";
  returnToRoleCreate?: boolean;
  returnToRoleId?: string;
  knowledgeRoleId?: string;
}) {
  const { t } = useLanguage();
  const router = useRouter();
  const [catalogRevision, setCatalogRevision] = useState(0);
  const { avatars: officialAvatars, personalAvatars, configured, loading: realtimeLoading, error: realtimeError } = useOfficialRealtimeAvatars(tab === "official-realtime", catalogRevision);
  if (tab === "avatars") return <AvatarResourceHome
    task={avatarTask}
    avatarId={initialAvatarId}
    actionId={initialActionId}
    method={initialTalkingMethod}
    returnToRoleId={returnToRoleId}
  />;
  const returnToRole = returnToRoleId ? () => router.push(`/roles/${encodeURIComponent(returnToRoleId)}`) : undefined;
  return <div className={styles.page}>
    {returnToRoleId ? <BackLink className={styles.returnLink} href={`/roles/${encodeURIComponent(returnToRoleId)}`} label={t("返回当前角色")} /> : null}
    {returnToRoleCreate ? <BackLink className={styles.returnLink} href="/roles/new" label={t("返回创建角色并选择资源")} /> : null}
    <section className={styles.content}>
      {tab === "voices" ? <VoiceLibrary /> : null}
      {tab === "personas" ? <PersonaLibraryScreen embedded onCreated={returnToRole} /> : null}
      {tab === "tools" ? <ToolLibraryScreen onCreated={returnToRole} /> : null}
      {tab === "memory" ? <MemorySettingsScreen initialRoleId={knowledgeRoleId ?? returnToRoleId} /> : null}
      {tab === "knowledge" ? <KnowledgeLibraryScreen onCreated={returnToRole} /> : null}
      {tab === "official-realtime" ? <div className={styles.realtimeHeading}>
        <h2>{t("实时数字人")}</h2>
        <button type="button" className={styles.realtimeCreate} disabled={realtimeLoading} onClick={() => setCatalogRevision((revision) => revision + 1)}>{t("刷新形象")}</button>
      </div> : null}
      {tab === "official-realtime" && realtimeError ? <div role="alert">
        <p>{t("同步 Anam 形象失败：")}{realtimeError}</p>
        <p>{t("请检查本地服务能否连接 Anam，以及个人 API Key 是否属于创建形象的同一账号或组织，然后刷新形象。")}</p>
        <Link href="/settings/providers" className={styles.realtimeCreate}>{t("检查个人 API Key")}</Link>
      </div> : null}
      {tab === "official-realtime" ? realtimeLoading ? <p>{t("正在读取实时数字人…")}</p> : configured ? <>
        {([{ title: t("我的数字人形象"), avatars: personalAvatars, collapsible: false }, { title: t("官方配置的数字人形象"), avatars: officialAvatars, collapsible: true }] as const).map((group) => {
          const cards = group.avatars.length ? <div className={styles.officialRealtimeGrid}>{group.avatars.map((avatar) => <Link key={avatar.id} className={styles.officialRealtimeCard}
            href={`/resources/realtime/${encodeURIComponent(avatar.id)}`}>
            <span className={styles.officialRealtimeImage}>{avatar.imageUrl ? <Image src={avatar.imageUrl} alt="" fill sizes="(max-width: 760px) 45vw, 210px" unoptimized /> : null}</span>
            <strong>{<LocalizedText text={avatar.displayName} />}</strong><small>{t("配置声音、人设和工具")}</small>
          </Link>)}</div> : <p>{t("暂无可用形象。")}</p>;
          return group.collapsible ? <details key={group.title} className={styles.realtimeSection} aria-label={group.title}>
            <summary>{<LocalizedText text={group.title} />}<small>{group.avatars.length}{t(" 个形象")}</small></summary>{cards}
          </details> : <section key={group.title} className={styles.realtimeSection} aria-label={group.title}>
            <div className={styles.realtimeHeading}><h2>{<LocalizedText text={group.title} />}</h2>{personalAvatars.length === 0 ? <Link href="/resources?tab=official-realtime&task=realtime" className={styles.realtimeCreate}><Plus aria-hidden="true" />{t("创建数字人")}</Link> : null}</div>{cards}
          </section>;
        })}
      </> : realtimeError ? null : <p>{t("配置 Anam 后，才可使用实时数字人。")}</p> : null}
    </section>
    {tab === "official-realtime" && avatarTask === "realtime" && configured && personalAvatars.length === 0 ? <AvatarUploadDialog
      mode="realtime"
      onClose={() => router.replace("/resources?tab=official-realtime", { scroll: false })}
      onRealtimeCreated={() => { setCatalogRevision((revision) => revision + 1); router.replace("/resources?tab=official-realtime", { scroll: false }); }}
    /> : null}
  </div>;
}

"use client";

import Link from "next/link";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Plus } from "lucide-react";
import { AvatarResourceHome } from "@/components/avatar/avatar-resource-home";
import { AvatarUploadDialog } from "@/components/avatar/avatar-upload-dialog";
import { PersonaLibraryScreen } from "@/components/persona/persona-library-screen";
import { ToolLibraryScreen } from "@/components/tools/tool-library-screen";
import { KnowledgeLibraryScreen } from "./knowledge-library-screen";
import { VoiceLibrary } from "./voice-library";
import { useOfficialRealtimeAvatars } from "@/hooks/use-official-realtime-avatars";
import type { AvatarWorkbenchTask } from "@/lib/avatar-workbench-navigation";
import styles from "./resource-library-screen.module.css";

export type ResourceTab = "voices" | "personas" | "tools" | "knowledge" | "avatars" | "official-realtime";

export function ResourceLibraryScreen({
  tab,
  avatarTask,
  initialAvatarId,
  initialActionId,
  initialTalkingMethod,
  returnToRoleCreate = false,
  returnToRoleId,
}: {
  tab: ResourceTab;
  avatarTask?: AvatarWorkbenchTask;
  initialAvatarId?: string;
  initialActionId?: string;
  initialTalkingMethod?: "lipforcing";
  returnToRoleCreate?: boolean;
  returnToRoleId?: string;
}) {
  const router = useRouter();
  const [catalogRevision, setCatalogRevision] = useState(0);
  const { avatars: officialAvatars, personalAvatars, configured, loading: realtimeLoading } = useOfficialRealtimeAvatars(tab === "official-realtime", catalogRevision);
  if (tab === "avatars") return <AvatarResourceHome
    task={avatarTask}
    avatarId={initialAvatarId}
    actionId={initialActionId}
    method={initialTalkingMethod}
    returnToRoleId={returnToRoleId}
  />;
  const returnToRole = returnToRoleId ? () => router.push(`/roles/${encodeURIComponent(returnToRoleId)}`) : undefined;
  return <div className={styles.page}>
    {returnToRoleId ? <Link className={styles.returnLink} href={`/roles/${encodeURIComponent(returnToRoleId)}`}>← 返回当前角色</Link> : null}
    {returnToRoleCreate ? <Link className={styles.returnLink} href="/roles/new">← 返回创建角色并选择资源</Link> : null}
    <section className={styles.content}>
      {tab === "voices" ? <VoiceLibrary /> : null}
      {tab === "personas" ? <PersonaLibraryScreen embedded onCreated={returnToRole} /> : null}
      {tab === "tools" ? <ToolLibraryScreen onCreated={returnToRole} /> : null}
      {tab === "knowledge" ? <KnowledgeLibraryScreen onCreated={returnToRole} /> : null}
      {tab === "official-realtime" ? realtimeLoading ? <p>正在读取实时数字人…</p> : configured ? <>
        {([{ title: "我的数字人形象", avatars: personalAvatars, collapsible: false }, { title: "官方配置的数字人形象", avatars: officialAvatars, collapsible: true }] as const).map((group) => {
          const cards = group.avatars.length ? <div className={styles.officialRealtimeGrid}>{group.avatars.map((avatar) => <Link key={avatar.id} className={styles.officialRealtimeCard}
            href={`/resources/realtime/${encodeURIComponent(avatar.id)}`}>
            <span className={styles.officialRealtimeImage}>{avatar.imageUrl ? <Image src={avatar.imageUrl} alt="" fill sizes="(max-width: 760px) 45vw, 210px" unoptimized /> : null}</span>
            <strong>{avatar.displayName}</strong><small>配置声音、人设和工具</small>
          </Link>)}</div> : <p>暂无可用形象。</p>;
          return group.collapsible ? <details key={group.title} className={styles.realtimeSection} aria-label={group.title}>
            <summary>{group.title}<small>{group.avatars.length} 个形象</small></summary>{cards}
          </details> : <section key={group.title} className={styles.realtimeSection} aria-label={group.title}>
            <div className={styles.realtimeHeading}><h2>{group.title}</h2><Link href="/resources?tab=official-realtime&task=realtime" className={styles.realtimeCreate}><Plus aria-hidden="true" />创建数字人</Link></div>{cards}
          </section>;
        })}
      </> : <p>配置 Anam 后，才可使用实时数字人。</p> : null}
    </section>
    {tab === "official-realtime" && avatarTask === "realtime" && configured ? <AvatarUploadDialog
      mode="realtime"
      onClose={() => router.replace("/resources?tab=official-realtime", { scroll: false })}
      onRealtimeCreated={() => { setCatalogRevision((revision) => revision + 1); router.replace("/resources?tab=official-realtime", { scroll: false }); }}
    /> : null}
  </div>;
}

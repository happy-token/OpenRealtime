"use client";

import { BackLink } from "@/components/workspace/back-link";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, Film, RefreshCw, Sparkles } from "lucide-react";
import type { AvatarAsset } from "@/lib/avatar-catalog";
import { isSegmentedAvatarAsset, loadCurrentAvatarCatalog, loadInternalPresetAvatars } from "@/lib/avatar-library-catalog-client";
import styles from "./production-service-screen.module.css";
import { PersonalVideoGeneration } from "./personal-video-generation";
import { AvatarActionStudio } from "@/components/avatar/avatar-action-studio";
import { AvatarLightweightConfig } from "@/components/avatar/avatar-lightweight-config";
import type { OwnedAvatarRecord } from "@/lib/avatar-records";
import { fetchOwnedAvatars, fetchPersonalAvatars } from "@/lib/avatar-catalog-client";

type ServiceKind = "motion" | "talking";
type ServiceState = { label: string; detail: string };

export function mergeAccessibleAvatarRecords(results: PromiseSettledResult<OwnedAvatarRecord[]>[]) {
  return {
    accessible: results.some((result) => result.status === "fulfilled"),
    avatars: results.flatMap((result) => result.status === "fulfilled" ? result.value : [])
      .filter((avatar) => !avatar.deleted_at),
  };
}

export function productionServiceHref(href: string, avatarId?: string, actionId?: string, returnTo?: string, method?: "lipforcing") {
  const params = new URLSearchParams();
  if (avatarId) params.set("avatar_id", avatarId);
  if (href === "/services/talking" && actionId) params.set("action_id", actionId);
  if (returnTo) params.set("return_to", returnTo);
  if (href === "/services/talking" && method) params.set("method", method);
  const query = params.toString();
  return query ? `${href}?${query}` : href;
}

const config = {
  motion: {
    eyebrow: "MOTION SERVICE",
    title: "动作生成",
    description: "选择数字人形象，使用 LivePortrait 或视频生成服务制作新的动作。",
    icon: Sparkles,
  },
  talking: {
    eyebrow: "TALKING MATERIALS",
    title: "口型对齐",
    description: "选择已有动作底片，制作与其配对的讲话版。",
    icon: Film,
  },
} as const;

export function ProductionServiceScreen({
  kind,
  initialAvatarId,
  initialActionId,
  initialTalkingMethod,
  returnToRoleId,
  returnToRoleCreate = false,
  onComplete,
}: {
  kind: ServiceKind;
  initialAvatarId?: string;
  initialActionId?: string;
  initialTalkingMethod?: "lipforcing";
  returnToRoleId?: string;
  returnToRoleCreate?: boolean;
  onComplete?: (result: { avatarId: string; actionId?: string }) => void;
}) {
  const [avatars, setAvatars] = useState<AvatarAsset[] | null>(null);
  const [ownedAvatars, setOwnedAvatars] = useState<OwnedAvatarRecord[]>([]);
  const [assetAccess, setAssetAccess] = useState<boolean | null>(null);
  const [status, setStatus] = useState<ServiceState>({ label: "检测中", detail: "正在检查服务状态" });
  const [selectedAvatarId, setSelectedAvatarId] = useState(initialAvatarId ?? "");
  const [ownedAvatar, setOwnedAvatar] = useState<OwnedAvatarRecord | null>(null);
  const [workspaceOpen, setWorkspaceOpen] = useState(Boolean(initialAvatarId));
  const [selectedActionId, setSelectedActionId] = useState(initialActionId ?? "");
  const [mobileConfigOpen, setMobileConfigOpen] = useState(false);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([
      Promise.allSettled([fetchOwnedAvatars(controller.signal), fetchPersonalAvatars(controller.signal)]),
      loadCurrentAvatarCatalog(controller.signal, { includeHostedAvatars: false, includeOwnedBuiltinActions: true }),
    ]).then(([avatarResults, items]) => {
      if (controller.signal.aborted) return;
      const accessible = mergeAccessibleAvatarRecords(avatarResults);
      setOwnedAvatars(accessible.avatars);
      setAssetAccess(accessible.accessible);
      setAvatars(items);
    }).catch(() => { if (!controller.signal.aborted) { setAssetAccess(false); setAvatars(loadInternalPresetAvatars()); } });
    const endpoint = kind === "motion" ? "/api/liveportrait" : "/api/services/talking/status";
    void fetch(endpoint, { signal: controller.signal, cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error("服务状态读取失败");
        const payload = await response.json() as {
          ready?: boolean; error?: string; issues?: string[];
          methods?: Record<string, { ready: boolean; detail: string }>;
        };
        if (controller.signal.aborted) return;
        if (kind === "motion") {
          setStatus(payload.ready
            ? { label: "可用", detail: "LivePortrait 已就绪；也可在创建页选择其他视频生成方式。" }
            : { label: "暂不可用", detail: payload.error || payload.issues?.[0] || "LivePortrait 尚未就绪；其他生成方式可在创建页查看。" });
        } else {
          const methods = payload.methods ?? {};
          const available = Object.entries(methods).filter(([, method]) => method.ready).map(([name]) => name === "wav2lip" ? "Wav2Lip" : name === "musetalk" ? "MuseTalk" : name === "lipforcing" ? "Lip Forcing" : "MiniMax");
          setStatus({
            label: payload.ready ? "可用" : "暂不可用",
            detail: available.length ? `${available.join("、")} 可用于制作口型对齐。` : methods.wav2lip?.detail || "口型对齐服务尚未就绪。",
          });
        }
      })
      .catch(() => { if (!controller.signal.aborted) setStatus({ label: "检测失败", detail: "无法读取服务状态，请稍后重试。" }); });
    return () => controller.abort();
  }, [kind, reload]);

  const refresh = useCallback(() => {
    setAvatars(null);
    setAssetAccess(null);
    setStatus({ label: "检测中", detail: "正在检查服务状态" });
    setReload((value) => value + 1);
  }, []);
  const availableAvatars = (avatars ?? []).filter((avatar) =>
    isSegmentedAvatarAsset(avatar) && ownedAvatars.some((item) => item.avatar_id === avatar.avatarId)
      && (kind === "talking" || avatar.canCreateActions));
  const selected = availableAvatars.find((avatar) => avatar.avatarId === selectedAvatarId) ?? availableAvatars[0];
  const selectedOwnedAvatar = ownedAvatars.find((avatar) => avatar.avatar_id === selected?.avatarId) ?? null;
  const actions = selectedOwnedAvatar?.actions.filter((action) => !action.deleted_at && action.video_url) ?? [];
  const view = config[kind];
  const Icon = view.icon;
  const returnTo = returnToRoleId ?? (returnToRoleCreate ? "role-create" : undefined);
  const serviceHref = (href: string) => productionServiceHref(href, selected?.avatarId, selectedActionId, returnTo, initialTalkingMethod);
  const returnHref = returnToRoleId ? `/roles/${encodeURIComponent(returnToRoleId)}` : returnToRoleCreate ? "/roles/new" : "/resources?tab=avatars";
  const returnLabel = returnToRoleId ? "返回当前角色" : returnToRoleCreate ? "返回创建角色" : "返回数字人";

  useEffect(() => { setOwnedAvatar(selectedOwnedAvatar); }, [selectedOwnedAvatar]);

  return <main className={styles.page}>
    <BackLink className={styles.back} href={returnHref} label={returnLabel} />
    <header className={styles.header}>
      <span className={styles.icon}><Icon /></span>
      <div><h1>{view.title}</h1><p>{kind === "motion" && assetAccess === false ? "上传参考图片，使用个人 MiniMax Key 生成可下载的动作视频。" : view.description}</p></div>
    </header>
    <div className={styles.switch} aria-label="制作服务">
      <Link href={serviceHref("/services/motion")} aria-current={kind === "motion" ? "page" : undefined}>动作生成</Link>
      <Link href={serviceHref("/services/talking")} aria-current={kind === "talking" ? "page" : undefined}>口型对齐</Link>
    </div>
    {assetAccess !== false ? <section className={styles.status} aria-label="服务状态">
      <div><span data-ready={status.label === "可用"}>{status.label}</span><p>{status.detail}</p></div>
      <button type="button" onClick={refresh} aria-label="重新检测服务"><RefreshCw /></button>
    </section> : null}
    {assetAccess === false && kind === "talking" ? <p className={styles.empty}>当前账户尚未开放数字人素材工作台。</p> : null}
    {assetAccess !== false ? <section className={styles.work}>
      <div className={styles.sectionHeading}><span>01 / 选择形象</span><h2>从已有数字人开始</h2><p>动作与口型对齐保存在所选形象下，可供多个角色复用。</p></div>
      {avatars === null ? <p className={styles.empty}>正在读取数字人形象…</p> : availableAvatars.length === 0
        ? <div className={styles.empty}>暂无可用形象。<Link href={productionServiceHref("/avatars/create", undefined, undefined, returnTo)}>创建数字人 <ArrowRight /></Link></div>
        : <div className={styles.avatarList} role="group" aria-label="选择数字人形象">
          {availableAvatars.map((avatar) => <button type="button" key={avatar.avatarId}
            data-selected={selected?.avatarId === avatar.avatarId}
            aria-pressed={selected?.avatarId === avatar.avatarId}
            onClick={() => { setSelectedAvatarId(avatar.avatarId); setWorkspaceOpen(false); setOwnedAvatar(null); }}>
            <strong>{avatar.displayName}</strong><small>{ownedAvatars.find((item) => item.avatar_id === avatar.avatarId)?.actions.filter((action) => !action.deleted_at && action.video_url).length ?? 0} 个动作底片</small>
          </button>)}
        </div>}
    </section> : null}
    {assetAccess !== false && selected ? <section className={styles.work}>
      <div className={styles.sectionHeading}><span>02 / 开始制作</span><h2>{kind === "motion" ? `为 ${selected.displayName} 创建动作` : `为 ${selected.displayName} 选择底片`}</h2>
        <p>{kind === "motion" ? "进入动作工作台后选择模板、上传参考或使用视频生成。" : "口型对齐会与所选动作配对，生成后可在形象详情中管理。"}</p></div>
      {kind === "motion" ? <button className={styles.primary} type="button" onClick={() => setWorkspaceOpen(true)}>打开动作工作台 <ArrowRight /></button>
        : actions.length ? <div className={styles.actionList}>{actions.map((action) => <button type="button" key={action.avatar_action_id}
          onClick={() => { setSelectedActionId(action.avatar_action_id); setWorkspaceOpen(true); }}>
          <Film /><span><strong>{action.display_name}</strong><small>使用此底片生成讲话版</small></span><ArrowRight />
        </button>)}</div>
          : <div className={styles.empty}>此形象还没有可用的动作底片。<Link href={serviceHref("/services/motion")}>先创建动作 <ArrowRight /></Link></div>}
    </section> : null}
    {workspaceOpen && selected ? <section className={styles.work} aria-label={kind === "motion" ? "动作生成工作台" : "口型对齐工作台"}>
      {kind === "motion" ? <AvatarActionStudio key={selected.avatarId} avatarId={selected.avatarId} embedded onChangeAvatar={() => setWorkspaceOpen(false)} mobileConfigOpen={mobileConfigOpen} onMobileConfigOpenChange={setMobileConfigOpen} onSaved={(action) => onComplete?.({ avatarId: selected.avatarId, actionId: action.avatar_action_id })} />
        : ownedAvatar ? <AvatarLightweightConfig key={ownedAvatar.avatar_id} avatar={ownedAvatar} active open={mobileConfigOpen} onOpenChange={setMobileConfigOpen} initialActionId={selectedActionId} initialMethod={initialTalkingMethod} previewBeforeSave header={<h2>动作编排 · 生成口型素材</h2>} onCreateAction={() => window.location.assign(serviceHref("/services/motion"))} onSaved={() => onComplete?.({ avatarId: ownedAvatar.avatar_id, actionId: selectedActionId || undefined })} />
          : <p className={styles.empty}>正在读取所选数字人…</p>}
    </section> : null}
    {kind === "motion" ? <PersonalVideoGeneration initialAvatarId={initialAvatarId} returnToRoleId={returnToRoleId} onActionSaved={(action) => onComplete?.({ avatarId: selected?.avatarId ?? initialAvatarId ?? "", actionId: action.avatar_action_id })} /> : null}
  </main>;
}

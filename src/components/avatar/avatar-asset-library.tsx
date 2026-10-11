"use client";
import { LocalizedText } from "@/components/language/language-provider";

import { useLanguage } from "@/components/language/language-provider";


import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowUpRight, AudioLines, Film, Maximize2, MessageCircle, Minimize2, MoreHorizontal, Plus, Search, Sparkles, Trash2, UserRound, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent } from "react";
import { createPortal } from "react-dom";
import type { AvatarAction, AvatarAsset } from "@/lib/avatar-catalog";
import { summarizeAvatarCapabilities } from "@/lib/avatar-catalog";
import { isSegmentedAvatarAsset } from "@/lib/avatar-library-catalog-client";
import { hideIdentityAsset, hideMotionAsset } from "@/lib/digital-human-asset-management";
import { fetchOwnedAvatar } from "@/lib/avatar-catalog-client";
import type { OwnedAvatarRecord } from "@/lib/avatar-records";
import { AvatarMediaCoverflow } from "./avatar-media-coverflow";
import { AvatarTalkingMaterialRail } from "./avatar-talking-material-rail";
import styles from "./avatar-asset-library.module.css";

export type AvatarLibraryScope = "realtime" | "internal-preset";
export type RealtimeAvatarScope = "custom" | "built-in";

type PendingAssetDeletion =
  | { kind: "avatar"; avatarId: string; displayName: string }
  | { kind: "action"; avatarId: string; avatarActionId: string; displayName: string };

export function shouldAutoAdvanceAvatarCardMedia({
  segmentedAsset,
  expanded,
  previewingAction,
  menuOpen,
  playableActionCount,
}: {
  segmentedAsset: boolean;
  expanded: boolean;
  previewingAction: boolean;
  menuOpen: boolean;
  playableActionCount: number;
}) {
  return segmentedAsset
    && !expanded
    && !previewingAction
    && !menuOpen
    && playableActionCount > 0;
}

export function avatarLibraryHref(scope: AvatarLibraryScope, realtimeScope: RealtimeAvatarScope, returnTo?: string) {
  const params = new URLSearchParams({ tab: "avatars", scope });
  if (scope === "realtime") params.set("realtime_scope", realtimeScope);
  if (returnTo) params.set("return_to", returnTo);
  return `/resources?${params.toString()}`;
}

export function AvatarAssetLibrary({
  avatars,
  internalPresetIds,
  initialScope = "realtime",
  initialRealtimeScope = "custom",
  loading = false,
  embedded = false,
  returnTo,
}: {
  avatars: AvatarAsset[];
  internalPresetIds: readonly string[];
  initialScope?: AvatarLibraryScope;
  initialRealtimeScope?: RealtimeAvatarScope;
  loading?: boolean;
  embedded?: boolean;
  returnTo?: string;
}) {
  const { t } = useLanguage();
  const router = useRouter();
  const [scope, setScope] = useState(initialScope);
  const [realtimeScope, setRealtimeScope] = useState(initialRealtimeScope);
  const [query, setQuery] = useState("");
  const [activeActionAvatarId, setActiveActionAvatarId] = useState<string | null>(null);
  const [hiddenAvatarIds, setHiddenAvatarIds] = useState<Set<string>>(() => new Set());
  const [hiddenActionIds, setHiddenActionIds] = useState<Set<string>>(() => new Set());
  const [pendingDeletion, setPendingDeletion] = useState<PendingAssetDeletion | null>(null);
  const internalPresetIdSet = useMemo(() => new Set(internalPresetIds), [internalPresetIds]);
  const libraryAvatars = useMemo(() => avatars
    .filter((avatar) => !hiddenAvatarIds.has(avatar.avatarId))
    .map((avatar) => ({
      ...avatar,
      actions: avatar.actions.filter((action) => !hiddenActionIds.has(action.avatarActionId)),
    })), [avatars, hiddenActionIds, hiddenAvatarIds]);
  const realtimeCount = useMemo(
    () => libraryAvatars.filter((avatar) => Boolean(avatar.realtimeBinding) && !avatar.deletedAt).length,
    [libraryAvatars],
  );
  const customRealtimeCount = useMemo(
    () => libraryAvatars.filter((avatar) => Boolean(avatar.realtimeBinding) && avatar.visibility === "private" && !avatar.deletedAt).length,
    [libraryAvatars],
  );
  const builtInRealtimeCount = realtimeCount - customRealtimeCount;
  const segmentedAvatarCount = useMemo(
    () => libraryAvatars.filter((avatar) => isSegmentedAvatarAsset(avatar, internalPresetIdSet)).length,
    [libraryAvatars, internalPresetIdSet],
  );
  const visibleAvatars = useMemo(() => libraryAvatars.filter((avatar) => {
    const inScope = scope === "realtime"
      ? Boolean(avatar.realtimeBinding) && (
        realtimeScope === "custom" ? avatar.visibility === "private" : avatar.visibility === "shared"
      )
      : isSegmentedAvatarAsset(avatar, internalPresetIdSet);
    if (!inScope || avatar.deletedAt) return false;
    const needle = query.trim().toLocaleLowerCase();
    return !needle
      || avatar.displayName.toLocaleLowerCase().includes(needle)
      || t(avatar.displayName).toLocaleLowerCase().includes(needle)
      || avatar.avatarId.toLocaleLowerCase().includes(needle);
  }), [internalPresetIdSet, libraryAvatars, query, realtimeScope, scope, t]);

  useEffect(() => {
    const activeAvatar = visibleAvatars.find((avatar) => avatar.avatarId === activeActionAvatarId);
    if (activeActionAvatarId && (!activeAvatar || !activeAvatar.actions.some((action) => action.state === "available" && !action.pendingModelCount && action.videoUrl))) {
      setActiveActionAvatarId(null);
    }
  }, [activeActionAvatarId, visibleAvatars]);

  useEffect(() => {
    if (!pendingDeletion) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPendingDeletion(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [pendingDeletion]);

  function confirmAssetDeletion() {
    if (!pendingDeletion) return;
    if (pendingDeletion.kind === "avatar") {
      hideIdentityAsset(pendingDeletion.avatarId);
      setHiddenAvatarIds((current) => new Set(current).add(pendingDeletion.avatarId));
    } else {
      hideMotionAsset(pendingDeletion.avatarActionId);
      setHiddenActionIds((current) => new Set(current).add(pendingDeletion.avatarActionId));
    }
    setActiveActionAvatarId(null);
    setPendingDeletion(null);
  }

  function selectScope(nextScope: AvatarLibraryScope) {
    setActiveActionAvatarId(null);
    setScope(nextScope);
    router.replace(avatarLibraryHref(nextScope, realtimeScope, returnTo), { scroll: false });
  }

  function selectRealtimeScope(nextScope: RealtimeAvatarScope) {
    setRealtimeScope(nextScope);
    router.replace(avatarLibraryHref("realtime", nextScope, returnTo), { scroll: false });
  }

  return (
    <section className={styles.library} data-embedded={embedded} aria-label={t("数字人资产")} aria-busy={loading || undefined}>
      <header className={styles.header}>
        <div className={styles.toolbar}>
          <div className={styles.scopeSwitch} aria-label={t("Avatar 分类")}>
            <span className={styles.scopeSwitchTrack} data-scope={scope} aria-hidden="true" />
            <button type="button" data-active={scope === "realtime"} aria-pressed={scope === "realtime"} onClick={() => selectScope("realtime")}>
              <Sparkles aria-hidden="true" />{t("实时驱动 ")}<em>{loading ? "…" : realtimeCount}</em>
            </button>
            <button type="button" data-active={scope === "internal-preset"} aria-pressed={scope === "internal-preset"} onClick={() => selectScope("internal-preset")}>
              <UserRound aria-hidden="true" />{t("内部预制 ")}<em>{loading ? "…" : segmentedAvatarCount}</em>
            </button>
          </div>
          <label className={styles.search}>
            <Search aria-hidden="true" />
            <span className="sr-only">{t("搜索 Avatar")}</span>
            <input
              value={query}
              disabled={loading}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t("搜索名称或 ID")}
            />
          </label>
          <Link className={styles.trashLink} href={appendReturnTo("/avatars/trash", returnTo)}><Trash2 />{t("回收站")}</Link>
          <Link className={styles.createButton} href={appendReturnTo("/avatars/create", returnTo)}>
            <Plus aria-hidden="true" />
            {t("创建数字人")}</Link>
        </div>
        <div className={styles.productionBar}>
          <div><Film aria-hidden="true" /><span><strong>{t("动作与口型对齐")}</strong><small>{t("素材归属于数字人；口型对齐继续归属于对应动作。")}</small></span></div>
          <nav aria-label={t("数字人素材制作")}>
            <Link href={appendReturnTo("/services/motion", returnTo)}><Sparkles aria-hidden="true" />{t("生成动作")}</Link>
            <Link href={appendReturnTo("/services/talking", returnTo)}><AudioLines aria-hidden="true" />{t("制作口型对齐")}</Link>
          </nav>
        </div>
      </header>

      {!loading && scope === "realtime" ? (
        <div className={styles.realtimeScope} aria-label={t("实时驱动分类")}>
          <div className={styles.realtimeScopeSwitch}>
            <span className={styles.realtimeScopeTrack} data-scope={realtimeScope} aria-hidden="true" />
            <button type="button" data-active={realtimeScope === "custom"} aria-pressed={realtimeScope === "custom"} onClick={() => selectRealtimeScope("custom")}>
              {t("自定义 Avatar")}<em>{customRealtimeCount}</em>
            </button>
            <button type="button" data-active={realtimeScope === "built-in"} aria-pressed={realtimeScope === "built-in"} onClick={() => selectRealtimeScope("built-in")}>
              {t("官方内置 Avatar")}<em>{builtInRealtimeCount}</em>
            </button>
          </div>
        </div>
      ) : null}

      {loading ? (
        <div className={styles.loadingGrid} role="status" aria-live="polite">
          <span className="sr-only">{t("正在加载数字人资产")}</span>
          {[0, 1, 2, 3].map((index) => <i key={index} aria-hidden="true" />)}
        </div>
      ) : visibleAvatars.length ? (
        <div className={styles.grid}>
          {visibleAvatars.map((avatar) => (
            <AvatarCard
              key={avatar.avatarId}
              avatar={avatar}
              internalPreset={internalPresetIdSet.has(avatar.avatarId)}
              segmentedAsset={isSegmentedAvatarAsset(avatar, internalPresetIdSet)}
              expanded={activeActionAvatarId === avatar.avatarId}
              returnTo={returnTo}
              onExpandedChange={(active) => setActiveActionAvatarId(active ? avatar.avatarId : null)}
              onDeleteAvatar={() => setPendingDeletion({
                kind: "avatar",
                avatarId: avatar.avatarId,
                displayName: avatar.displayName,
              })}
              onDeleteAction={(action) => setPendingDeletion({
                kind: "action",
                avatarId: avatar.avatarId,
                avatarActionId: action.avatarActionId,
                displayName: action.displayName,
              })}
            />
          ))}
        </div>
      ) : (
        <div className={styles.empty}>
          <Sparkles aria-hidden="true" />
          <h2>{query ? t("没有匹配的 Avatar") : scope === "realtime" ? realtimeScope === "custom" ? t("暂无自定义实时 Avatar") : t("暂无官方内置 Avatar") : t("暂无内部预制形象")}</h2>
          <p>{query ? t("尝试搜索其他名称或 ID。") : scope === "realtime" ? realtimeScope === "custom" ? t("创建或接入实时驱动 Avatar 后会显示在这里。") : t("供应商内置 Avatar 加载后会显示在这里。") : t("内部预制形象加载后会显示在这里。")}</p>
          {!query && scope === "realtime" ? <Link href={appendReturnTo("/avatars/create", returnTo)}>{t("开始创建")}</Link> : null}
        </div>
      )}

      {pendingDeletion && typeof document !== "undefined" ? createPortal(
        <div
          className={styles.deleteDialogBackdrop}
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setPendingDeletion(null);
          }}
        >
          <section className={styles.deleteDialog} role="dialog" aria-modal="true" aria-labelledby="delete-avatar-asset-title">
            <span className={styles.deleteDialogIcon}><Trash2 aria-hidden="true" /></span>
            <div>
              <p>{pendingDeletion.kind === "avatar" ? "DELETE AVATAR" : "DELETE ACTION"}</p>
              <h2 id="delete-avatar-asset-title">{pendingDeletion.kind === "avatar" ? t("删除数字人形象？") : t("删除数字人动作？")}</h2>
              <span>
                {pendingDeletion.kind === "avatar"
                  ? t("删除“") + (pendingDeletion.displayName) + t("”后，这个形象及其动作会从内部预置资产中移除。")
                  : t("删除动作“") + (pendingDeletion.displayName) + t("”后，数字人形象和其他动作不受影响。")}
              </span>
            </div>
            <footer>
              <button type="button" onClick={() => setPendingDeletion(null)}>{t("取消")}</button>
              <button type="button" data-danger="true" onClick={confirmAssetDeletion}>{t("确认删除")}</button>
            </footer>
          </section>
        </div>,
        document.body,
      ) : null}
    </section>
  );
}

function AvatarCard({
  avatar,
  internalPreset,
  segmentedAsset,
  expanded,
  returnTo,
  onExpandedChange,
  onDeleteAvatar,
  onDeleteAction,
}: {
  avatar: AvatarAsset;
  internalPreset: boolean;
  segmentedAsset: boolean;
  expanded: boolean;
  returnTo?: string;
  onExpandedChange: (active: boolean) => void;
  onDeleteAvatar: () => void;
  onDeleteAction: (action: AvatarAction) => void;
}) {
  const { t } = useLanguage();
  const summary = summarizeAvatarCapabilities(avatar);
  const startHref = `/conversation?avatar_id=${encodeURIComponent(avatar.avatarId)}&experience=avatar`;
  const detailQuery = segmentedAsset
    ? "return_scope=internal-preset"
    : `return_scope=realtime&return_realtime_scope=${avatar.visibility === "private" ? "custom" : "built-in"}`;
  const detailHref = appendReturnTo(`/avatars/${encodeURIComponent(avatar.avatarId)}?${detailQuery}`, returnTo);
  const playableActions = useMemo(
    () => avatar.actions.filter((action) => action.state === "available" && !action.pendingModelCount && Boolean(action.videoUrl)),
    [avatar.actions],
  );
  const [activeMediaIndex, setActiveMediaIndex] = useState(0);
  const [previewAction, setPreviewAction] = useState<AvatarAction | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [ownedAvatar, setOwnedAvatar] = useState<OwnedAvatarRecord | null>(null);
  const [materialsLoading, setMaterialsLoading] = useState(false);
  const [materialsError, setMaterialsError] = useState("");
  const [materialsRefresh, setMaterialsRefresh] = useState(0);
  const [selectedTalkingVariantId, setSelectedTalkingVariantId] = useState<string | null>(null);
  const [materialMenuOpen, setMaterialMenuOpen] = useState(false);
  const detailLinkRef = useRef<HTMLAnchorElement>(null);
  const activeAction = activeMediaIndex > 0 ? playableActions[activeMediaIndex - 1] ?? null : null;
  const ownedAction = ownedAvatar?.actions.find(action => action.avatar_action_id === activeAction?.avatarActionId && !action.deleted_at);
  const talkingAction = activeAction ? ownedAction ?? {
    avatar_action_id: activeAction.avatarActionId,
    display_name: activeAction.displayName,
    video_url: activeAction.videoUrl,
    pending_model_count: activeAction.pendingModelCount,
    created_at: "",
    deleted_at: null,
    talking_variants: [],
  } : null;
  const selectedTalkingVariant = talkingAction?.talking_variants?.find(variant => variant.id === selectedTalkingVariantId && !variant.deleted_at) ?? null;

  function openDetailFromCard(event: ReactMouseEvent<HTMLElement>) {
    const target = event.target;
    if (!(target instanceof Element) || target.closest("a, button, input, textarea, select, video")) return;
    detailLinkRef.current?.click();
  }

  useEffect(() => {
    if (activeMediaIndex <= playableActions.length) return;
    setActiveMediaIndex(0);
  }, [activeMediaIndex, playableActions.length]);

  useEffect(() => {
    if (!expanded) setMaterialMenuOpen(false);
  }, [expanded]);

  useEffect(() => {
    if (!materialMenuOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === "Escape") setMaterialMenuOpen(false); };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [materialMenuOpen]);

  useEffect(() => {
    if (!expanded || !segmentedAsset) return;
    const controller = new AbortController();
    setMaterialsLoading(true);
    setMaterialsError("");
    void fetchOwnedAvatar(avatar.avatarId, controller.signal).then(record => {
      if (!controller.signal.aborted) setOwnedAvatar(record);
    }).catch(error => {
      if (!controller.signal.aborted) setMaterialsError(error instanceof Error ? error.message : "口型对齐读取失败");
    }).finally(() => {
      if (!controller.signal.aborted) setMaterialsLoading(false);
    });
    return () => controller.abort();
  }, [avatar.avatarId, expanded, materialsRefresh, segmentedAsset]);

  useEffect(() => {
    if (!shouldAutoAdvanceAvatarCardMedia({
      segmentedAsset,
      expanded,
      previewingAction: Boolean(previewAction),
      menuOpen,
      playableActionCount: playableActions.length,
    })) return;
    const timer = window.setTimeout(() => {
      setActiveMediaIndex((current) => (current + 1) % (playableActions.length + 1));
    }, 3_000);
    return () => window.clearTimeout(timer);
  }, [activeMediaIndex, expanded, menuOpen, playableActions.length, previewAction, segmentedAsset]);

  useEffect(() => {
    if (!previewAction && !menuOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setPreviewAction(null);
        setMenuOpen(false);
      }
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [menuOpen, previewAction]);

  return (
    <>
      <article
        className={styles.card}
        data-source={avatar.source.kind}
        data-internal-preset={internalPreset}
        data-preview-kind={activeAction ? "action" : "image"}
        data-expanded={expanded}
        data-material-open={expanded && materialMenuOpen}
        data-clickable={!expanded}
        data-menu-open={menuOpen}
        onClick={expanded ? undefined : openDetailFromCard}
      >
        <div className={styles.visual}>
          {segmentedAsset && expanded && playableActions.length ? (
            <div className={styles.expandedLayout}>
              <div className={styles.expandedPreview}>
                {selectedTalkingVariant ? <div className={styles.talkingPreview}>
                  <Image className={styles.talkingBackdrop} src={avatar.source.imageUrl} alt="" fill sizes="100vw" unoptimized />
                  <video key={selectedTalkingVariant.id} src={selectedTalkingVariant.video_url} aria-label={"" + (avatar.displayName) + " · " + (selectedTalkingVariant.display_name) + t(" 口型对齐")} autoPlay muted loop playsInline controls preload="auto" />
                </div> : <AvatarMediaCoverflow
                  avatarId={avatar.avatarId}
                  avatarName={t(avatar.displayName)}
                  imageUrl={avatar.source.imageUrl}
                  actions={playableActions}
                  activeIndex={activeMediaIndex}
                  active={!previewAction}
                  size="workbench"
                  onActiveIndexChange={index => { setActiveMediaIndex(index); setSelectedTalkingVariantId(null); }}
                  onCurrentActionClick={setPreviewAction}
                />}
              </div>
            </div>
          ) : (
            <div
              className={styles.media}
              data-has-actions={segmentedAsset && playableActions.length > 0}
              data-preview-kind={activeAction ? "action" : "image"}
            >
              {activeAction?.videoUrl ? (
                <>
                  <Image
                    className={styles.collapsedActionBackdrop}
                    src={avatar.source.imageUrl}
                    alt=""
                    aria-hidden="true"
                    fill
                    sizes="(max-width: 760px) 100vw, (max-width: 1200px) 50vw, 33vw"
                    unoptimized
                  />
                  <video
                    key={activeAction.avatarActionId}
                    className={styles.collapsedActionVideo}
                    src={activeAction.videoUrl}
                    poster={avatar.source.imageUrl}
                    aria-label={`${avatar.displayName} · ${activeAction.displayName}`}
                    autoPlay
                    muted
                    loop
                    playsInline
                    preload="auto"
                  />
                </>
              ) : (
                <>
                  <Image
                    className={styles.portraitBackdrop}
                    src={avatar.source.imageUrl}
                    alt=""
                    aria-hidden="true"
                    fill
                    sizes="(max-width: 760px) 100vw, (max-width: 1200px) 50vw, 33vw"
                    unoptimized
                  />
                  <Image
                    className={styles.portraitImage}
                    src={avatar.source.imageUrl}
                    alt={"" + (t(avatar.displayName)) + t(" 形象")}
                    fill
                    sizes="(max-width: 760px) 100vw, (max-width: 1200px) 50vw, 33vw"
                    unoptimized
                  />
                </>
              )}
            </div>
          )}
          {segmentedAsset && playableActions.length ? <button
            className={styles.materialTrigger}
            type="button"
            aria-label={t("选择 ") + (t(avatar.displayName)) + t(" 的口型对齐")}
            aria-expanded={expanded && materialMenuOpen}
            onClick={() => {
              if (!expanded) {
                setActiveMediaIndex(activeAction ? activeMediaIndex : 1);
                setSelectedTalkingVariantId(null);
                setMaterialMenuOpen(true);
                onExpandedChange(true);
              } else {
                setMaterialMenuOpen(open => !open);
              }
            }}
          ><Film aria-hidden="true" />{t("口型对齐")}</button> : null}
          {expanded && materialMenuOpen && talkingAction ? materialsError ? <div className={styles.materialsSideState} role="alert">
            <span>{materialsError}</span><button type="button" onClick={() => setMaterialsRefresh(value => value + 1)}>{t("重试")}</button>
          </div> : materialsLoading ? <div className={styles.materialsSideState} role="status">{t("正在读取口型对齐…")}</div> : <AvatarTalkingMaterialRail
            key={talkingAction.avatar_action_id}
            avatarId={avatar.avatarId}
            action={talkingAction}
            returnTo={returnTo}
            canManage={Boolean(ownedAction) && !avatar.avatarId.startsWith("avatar-personal-")}
            selectedVariantId={selectedTalkingVariant?.id ?? null}
            onSelect={variantId => {
              setSelectedTalkingVariantId(variantId);
              if (window.matchMedia("(max-width: 680px)").matches) setMaterialMenuOpen(false);
            }}
            onActionUpdated={updated => setOwnedAvatar(current => current ? {
              ...current,
              actions: current.actions.map(action => action.avatar_action_id === updated.avatar_action_id ? updated : action),
            } : current)}
          /> : null}
          <div className={styles.mediaMeta}>
            {segmentedAsset && playableActions.length ? (
              <button type="button" aria-label={t("管理 ") + (t(avatar.displayName)) + t(" 的动作")} onClick={() => {
                setActiveMediaIndex(1);
                setSelectedTalkingVariantId(null);
                onExpandedChange(true);
              }}>
                {playableActions.length} {t("个动作")}</button>
            ) : (
              <span data-muted={segmentedAsset && !playableActions.length}>
                {segmentedAsset ? t("未创建动作") : summary.realtimeLabel || summary.actionLabel}
              </span>
            )}
            {!internalPreset && summary.realtimeLabel && avatar.canCreateActions && avatar.actions.length
              ? <span>{summary.actionLabel}</span>
              : null}
            {!internalPreset && summary.pendingActionCount > 0 ? <span data-progress="true">{summary.pendingActionCount}{t(" 个动作待适配")}</span> : null}
          </div>
          <div className={styles.body}>
            <div className={styles.titleRow}>
              <div className={styles.titleBlock}>
                <h2>
                  <Link
                    ref={detailLinkRef}
                    className={styles.titleLink}
                    href={detailHref}
                    aria-label={t("查看 ") + (t(avatar.displayName)) + t(" 详情")}
                  >
                    {t(avatar.displayName)}
                  </Link>
                </h2>
                {!expanded && segmentedAsset && activeAction ? <small>{t("动作 · ") + (activeAction.displayName) + ""}</small> : null}
              </div>
              {expanded ? <div className={styles.actions}>
                <Link className={styles.primaryAction} href={startHref} aria-label={t("与 {name} 对话", { name: t(avatar.displayName) })}><MessageCircle aria-hidden="true" />{t("对话")}</Link>
                <Link className={`${styles.secondaryAction} ${styles.iconAction}`} href={avatar.avatarId.startsWith("avatar-personal-") ? appendReturnTo(`/services/motion?avatar_id=${encodeURIComponent(avatar.avatarId)}`, returnTo) : appendReturnTo(`/avatars/create?task=action&avatar_id=${encodeURIComponent(avatar.avatarId)}`, returnTo)} aria-label={t("为 ") + (t(avatar.displayName)) + t(" 创建动作")} title={t("创建动作")}><Plus aria-hidden="true" /></Link>
                <Link className={styles.detailLink} href={detailHref} aria-label={t("打开 ") + (t(avatar.displayName)) + t(" 详情")} title={t("查看详情")}><ArrowUpRight aria-hidden="true" /></Link>
                {segmentedAsset && expanded && activeAction ? (
                  <>
                    <Link className={`${styles.secondaryAction} ${styles.iconAction}`} href={talkingCreationHref(avatar, activeAction, returnTo)} aria-label={t("为 ") + (activeAction.displayName) + t(" 制作口型对齐")} title={t("制作口型对齐")}><AudioLines aria-hidden="true" /></Link>
                    {!selectedTalkingVariant ? <button
                      className={`${styles.secondaryAction} ${styles.iconAction}`}
                      type="button"
                      aria-label={t("放大预览：") + (activeAction.displayName) + ""}
                      title={t("放大预览")}
                      onClick={() => setPreviewAction(activeAction)}
                    >
                      <Maximize2 aria-hidden="true" />
                    </button> : null}
                    {internalPreset ? <button className={`${styles.deleteAvatarButton} ${styles.iconAction}`} type="button" aria-label={t("删除动作：") + (activeAction.displayName) + ""} title={t("删除动作")} onClick={() => onDeleteAction(activeAction)}>
                      <Trash2 aria-hidden="true" />
                    </button> : null}
                  </>
                ) : internalPreset ? (
                  <button className={`${styles.deleteAvatarButton} ${styles.iconAction}`} type="button" aria-label={t("删除形象：") + (t(avatar.displayName)) + ""} title={t("删除形象")} onClick={onDeleteAvatar}>
                    <Trash2 aria-hidden="true" />
                  </button>
                ) : null}
                {segmentedAsset && expanded ? (
                  <button className={`${styles.secondaryAction} ${styles.iconAction}`} type="button" aria-label={t("收起 ") + (t(avatar.displayName)) + t(" 的形象和动作")} title={t("收起预览")} onClick={() => { setSelectedTalkingVariantId(null); setMaterialMenuOpen(false); onExpandedChange(false); }}>
                    <Minimize2 aria-hidden="true" />
                  </button>
                ) : null}
              </div> : (
                <div className={styles.collapsedActions}>
                  <Link className={`${styles.quickStart} liquid-glass-button`} data-variant="primary" href={startHref} aria-label={t("与 {name} 对话", { name: t(avatar.displayName) })}><MessageCircle aria-hidden="true" />{t("对话")}</Link>
                  <button className={styles.moreButton} type="button" aria-label={t("更多操作：") + (t(avatar.displayName)) + ""} aria-expanded={menuOpen} onClick={() => setMenuOpen((open) => !open)}>
                    <MoreHorizontal aria-hidden="true" />
                  </button>
                </div>
              )}
            </div>
          </div>
          {!expanded ? (
            <div className={styles.actionMenu} aria-label={"" + (t(avatar.displayName)) + t(" 操作菜单")} hidden={!menuOpen}>
              <Link href={startHref} aria-label={t("与 {name} 对话", { name: t(avatar.displayName) })}>{t("开始对话")}</Link>
              {internalPreset || (avatar.visibility === "private" && avatar.canCreateActions) ? <Link href={avatar.avatarId.startsWith("avatar-personal-") ? appendReturnTo(`/services/motion?avatar_id=${encodeURIComponent(avatar.avatarId)}`, returnTo) : appendReturnTo(`/avatars/create?task=action&avatar_id=${encodeURIComponent(avatar.avatarId)}`, returnTo)} aria-label={t("为 ") + (t(avatar.displayName)) + t(" 创建动作")}>{t("创建动作")}</Link> : null}
              <Link href={detailHref} aria-label={t("打开 ") + (t(avatar.displayName)) + t(" 详情")}>{t("查看详情")}</Link>
              {internalPreset ? <button type="button" aria-label={t("删除形象：") + (t(avatar.displayName)) + ""} onClick={onDeleteAvatar}>{t("删除 Avatar")}</button> : null}
            </div>
          ) : null}
        </div>
      </article>

      {previewAction && typeof document !== "undefined" ? createPortal(
        <div
          className={styles.actionModalBackdrop}
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setPreviewAction(null);
          }}
        >
          <section
            className={styles.actionModal}
            role="dialog"
            aria-modal="true"
            aria-label={"" + (previewAction.displayName) + t(" 动作预览")}
          >
            <Image className={styles.actionModalBackdropImage} src={avatar.source.imageUrl} alt="" aria-hidden="true" fill sizes="100vw" unoptimized />
            <span className={styles.actionModalScrim} aria-hidden="true" />
            <header>
              <div className={styles.actionModalTitle}>
                <span><Film aria-hidden="true" /></span>
                <div>
                  <p>{t(avatar.displayName)}{t(" · 动作预览")}</p>
                  <h2>{<LocalizedText text={previewAction.displayName} />}</h2>
                </div>
              </div>
              <button type="button" aria-label={t("关闭动作预览")} onClick={() => setPreviewAction(null)}>
                <X aria-hidden="true" />
              </button>
            </header>
            <div className={styles.actionModalMedia}>
              <div className={styles.actionModalStage}>
                {previewAction.videoUrl ? (
                  <video
                    src={previewAction.videoUrl}
                    aria-label={`${avatar.displayName} · ${previewAction.displayName}`}
                    controls
                    autoPlay
                    muted
                    loop
                    playsInline
                    preload="auto"
                  />
                ) : (
                  <span className={styles.actionModalFallback}><Film aria-hidden="true" />{t("暂无可预览视频")}</span>
                )}
              </div>
            </div>
            <footer className={styles.actionModalFooter}>
              <span><Film aria-hidden="true" />{t("当前动作")}</span>
              <p>{t("自动循环播放 · 可使用播放器控制进度、音量和全屏显示")}</p>
            </footer>
          </section>
        </div>,
        document.body,
      ) : null}
    </>
  );
}

function appendReturnTo(href: string, returnTo?: string) {
  if (!returnTo) return href;
  return `${href}${href.includes("?") ? "&" : "?"}return_to=${encodeURIComponent(returnTo)}`;
}

export function talkingCreationHref(avatar: AvatarAsset, action: AvatarAction, returnTo?: string) {
  const href = avatar.avatarId.startsWith("avatar-personal-")
    ? `/services/talking?avatar_id=${encodeURIComponent(avatar.avatarId)}&action_id=${encodeURIComponent(action.avatarActionId)}`
    : `/avatars/create?task=lightweight&avatar_id=${encodeURIComponent(avatar.avatarId)}&avatar_action_id=${encodeURIComponent(action.avatarActionId)}`;
  return appendReturnTo(href, returnTo);
}

"use client";

import { BackLink } from "@/components/workspace/back-link";

import Image from "next/image";
import Link from "next/link";
import { AlertTriangle, Check, ChevronDown, Film, ImageIcon, ImagePlus, LoaderCircle, MessageCircle, Pencil, Radio, Sparkles, Trash2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  fetchOwnedAvatar,
  renameOwnedAvatar,
  replaceOwnedAvatarSourceImage,
  setOwnedAvatarDeletion,
  updateOwnedAvatarAction,
} from "@/lib/avatar-catalog-client";
import { normalizeAvatarSourceImage } from "@/lib/avatar-image-normalization";
import { loadCurrentAvatarCatalog } from "@/lib/avatar-library-catalog-client";
import type { OwnedAvatarActionRecord, OwnedAvatarRecord } from "@/lib/avatar-records";
import type { AvatarPersonaProfile } from "@/lib/avatar-persona";
import { parseAvatarDisplayConfig } from "@/components/digital-human/types";
import { AVATAR_DISPLAY_CONFIG_STORAGE_KEY } from "@/lib/avatar-identity-sync";
import { reconcileAvatarDisplayConfigWithOwnedAvatar } from "@/lib/avatar-session-config";
import { readJsonResponse } from "@/lib/http-json-response";
import { AvatarTalkingMaterialRail } from "./avatar-talking-material-rail";
import styles from "./avatar-detail-screen.module.css";

type AvatarDetailRecord = OwnedAvatarRecord & {
  canCreateActions: boolean;
  canRename: boolean;
  canDeleteActions: boolean;
  canDelete: boolean;
  ownedActionIds: string[];
};

type ReplacementCandidate = {
  dataUrl: string;
  fileName: string;
};

type ActionRenameTarget = {
  avatarActionId: string;
  originalName: string;
};

type AvatarDetailLoadState = {
  avatarId: string;
  status: "loading" | "loaded";
  avatar: AvatarDetailRecord | null;
};

function normalizeAvatarActionName(displayName: string) {
  return displayName.normalize("NFKC").trim().toLocaleLowerCase();
}

export function avatarDetailActionHref(href: string, returnTo?: string) {
  if (!returnTo) return href;
  return `${href}${href.includes("?") ? "&" : "?"}return_to=${encodeURIComponent(returnTo)}`;
}

export function dedupeAvatarActionsByDisplayName(actions: readonly OwnedAvatarActionRecord[]) {
  const deduped: OwnedAvatarActionRecord[] = [];
  const indexByName = new Map<string, number>();

  for (const action of actions) {
    const key = normalizeAvatarActionName(action.display_name);
    const existingIndex = indexByName.get(key);
    if (existingIndex === undefined) {
      indexByName.set(key, deduped.length);
      deduped.push(action);
      continue;
    }

    const existing = deduped[existingIndex];
    const shouldReplace = !Boolean(existing.video_url) && Boolean(action.video_url);
    if (shouldReplace) {
      deduped[existingIndex] = action;
    }
  }

  return deduped;
}

export function ActionDockPreview({
  src,
  poster,
  label,
  playing,
  pageVisible = true,
  startDelayMs = 0,
}: {
  src: string;
  poster: string;
  label: string;
  playing: boolean;
  pageVisible?: boolean;
  startDelayMs?: number;
}) {
  const video = useRef<HTMLVideoElement>(null);
  const [withinViewport, setWithinViewport] = useState(false);
  const [ambientPlaybackReady, setAmbientPlaybackReady] = useState(false);
  const shouldPlay = shouldPlayAvatarActionDockPreview({
    engaged: playing,
    withinViewport,
    ambientPlaybackReady,
    pageVisible,
  });

  useEffect(() => {
    const element = video.current;
    if (!element) return;
    if (!("IntersectionObserver" in window)) {
      setWithinViewport(true);
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => setWithinViewport(Boolean(entry?.isIntersecting && entry.intersectionRatio >= 0.35)),
      { root: element.closest('[aria-label="形象和动作切换"]'), threshold: [0, 0.35] },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [src]);

  useEffect(() => {
    if (!withinViewport) {
      setAmbientPlaybackReady(false);
      return;
    }
    const timer = window.setTimeout(() => setAmbientPlaybackReady(true), startDelayMs);
    return () => window.clearTimeout(timer);
  }, [startDelayMs, withinViewport]);

  useEffect(() => {
    const element = video.current;
    if (!element) return;
    if (shouldPlay) {
      void element.play().catch(() => undefined);
      return;
    }
    element.pause();
  }, [shouldPlay, src]);

  return <video
    ref={video}
    src={src}
    poster={poster}
    aria-label={label}
    autoPlay={shouldPlay}
    muted
    loop
    playsInline
    disablePictureInPicture
    preload={shouldPlay ? "auto" : "none"}
    data-playing={shouldPlay}
    data-ambient-visible={withinViewport}
  />;
}

export function shouldPlayAvatarActionDockPreview(input: {
  engaged: boolean;
  withinViewport: boolean;
  ambientPlaybackReady: boolean;
  pageVisible: boolean;
}) {
  return input.pageVisible
    && input.withinViewport
    && (input.engaged || input.ambientPlaybackReady);
}

export function canDeleteAvatarAction(ownedActionIds: readonly string[], activeActionId: string | null) {
  return Boolean(activeActionId && ownedActionIds.includes(activeActionId));
}

export function AvatarAssetDeleteButton({
  avatarName,
  busy,
  onDelete,
}: {
  avatarName: string;
  busy: boolean;
  onDelete: () => void;
}) {
  return <button
    className={styles.deleteAvatarAction}
    type="button"
    aria-label={`删除数字人资产：${avatarName}`}
    title="将数字人资产移入回收站"
    disabled={busy}
    onClick={onDelete}
  >{busy ? <LoaderCircle className={styles.spin} /> : <Trash2 />}<span>{busy ? "正在删除数字人" : "删除数字人"}</span></button>;
}

export function getAvatarActionDockWheelDelta(deltaX: number, deltaY: number) {
  return Math.abs(deltaX) > Math.abs(deltaY) ? deltaX : deltaY;
}

export function shouldAutoAdvanceAvatarDetailMedia(input: {
  hasAvatar: boolean;
  actionCount: number;
  pageVisible: boolean;
  autoAdvancePinned: boolean;
  dockHovered: boolean;
  dockFocused: boolean;
  activeActionId: string | null;
  activeActionVideoUrl: string | null;
  readyStageActionId: string | null;
}) {
  if (!input.hasAvatar || input.actionCount === 0 || !input.pageVisible) return false;
  if (input.autoAdvancePinned || input.dockHovered || input.dockFocused) return false;
  return !input.activeActionVideoUrl || input.readyStageActionId === input.activeActionId;
}

export function AvatarActionRenameDialog({
  actionName,
  assetKind = "action",
  value,
  busy,
  error,
  onValueChange,
  onCancel,
  onSubmit,
}: {
  actionName: string;
  assetKind?: "action" | "avatar";
  value: string;
  busy: boolean;
  error: string;
  onValueChange: (value: string) => void;
  onCancel: () => void;
  onSubmit: () => void;
}) {
  const trimmedValue = value.trim();
  const isAvatar = assetKind === "avatar";
  const titleId = isAvatar ? "avatar-name-rename-title" : "avatar-action-rename-title";
  return (
    <div className={styles.replacementBackdrop} role="presentation" onMouseDown={(event) => event.target === event.currentTarget && !busy && onCancel()}>
      <form
        className={`${styles.replacementDialog} ${styles.renameDialog}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
      >
        <header>
          <span><Pencil /></span>
          <div><h2 id={titleId}>{isAvatar ? "修改数字人名称" : "修改动作名称"}</h2></div>
          <button type="button" aria-label={isAvatar ? "关闭数字人名称修改" : "关闭动作名称修改"} disabled={busy} onClick={onCancel}><X /></button>
        </header>
        <label className={styles.renameField}>
          <span>{isAvatar ? "数字人名称" : "动作名称"}</span>
          <input
            autoFocus
            aria-label={isAvatar ? "新的数字人名称" : "新的动作名称"}
            value={value}
            maxLength={50}
            disabled={busy}
            onChange={(event) => onValueChange(event.target.value)}
            onKeyDown={(event) => event.key === "Escape" && !busy && onCancel()}
          />
          <small>{value.length}/50</small>
        </label>
        <p className={styles.renameHint}>{isAvatar
          ? "仅修改显示名称，不会改变数字人 ID、形象图片、动作或模型。"
          : "仅修改列表中的显示名称，不会重新生成视频或影响口型模型。"}</p>
        {error ? <p className={styles.replacementDialogError} role="alert">{error}</p> : null}
        <footer>
          <button type="button" disabled={busy} onClick={onCancel}>取消</button>
          <button type="submit" disabled={busy || !trimmedValue || trimmedValue === actionName}>
            {busy ? <><LoaderCircle className={styles.spin} />正在保存</> : "保存名称"}
          </button>
        </footer>
      </form>
    </div>
  );
}

export function AvatarPersonaStatus({
  avatarId,
  avatarName,
  realtimeBound,
  linkedPersonaName,
  personaChecked,
}: {
  avatarId: string;
  avatarName: string;
  realtimeBound: boolean;
  linkedPersonaName: string | null;
  personaChecked: boolean;
}) {
  if (!realtimeBound && !linkedPersonaName && !personaChecked) return null;
  const personaHref = `/personas?avatar_id=${encodeURIComponent(avatarId)}&avatar_display_name=${encodeURIComponent(avatarName)}`;
  return (
    <div className={styles.statuses}>
      {realtimeBound ? <span><Radio />Anam 实时</span> : null}
      {linkedPersonaName ? (
        <span>
          <Sparkles />默认 Persona：{linkedPersonaName}
          <Link href={personaHref}>更换</Link>
        </span>
      ) : personaChecked ? (
        <span>
          <Sparkles />未关联 Persona
          <Link href={personaHref}>关联 Persona</Link>
        </span>
      ) : null}
    </div>
  );
}

export function AvatarDetailScreen({ avatarId, backHref = "/avatars", initialActionId, returnTo }: { avatarId: string; backHref?: string; initialActionId?: string; returnTo?: string }) {
  const [detailState, setDetailState] = useState<AvatarDetailLoadState>(() => ({
    avatarId,
    status: "loading",
    avatar: null,
  }));
  const [activeMediaIndex, setActiveMediaIndex] = useState(0);
  const [autoAdvancePinned, setAutoAdvancePinned] = useState(false);
  const [dockHovered, setDockHovered] = useState(false);
  const [dockFocused, setDockFocused] = useState(false);
  const [previewMediaIndex, setPreviewMediaIndex] = useState<number | null>(null);
  const [pageVisible, setPageVisible] = useState(true);
  const [readyStageActionId, setReadyStageActionId] = useState<string | null>(null);
  const [selectedTalkingVariantId, setSelectedTalkingVariantId] = useState<string | null>(null);
  const [replacementCandidate, setReplacementCandidate] = useState<ReplacementCandidate | null>(null);
  const [trashActionsOnReplace, setTrashActionsOnReplace] = useState(true);
  const [replacementBusy, setReplacementBusy] = useState(false);
  const [actionDeletionBusy, setActionDeletionBusy] = useState(false);
  const [avatarDeletionBusy, setAvatarDeletionBusy] = useState(false);
  const [actionRenameTarget, setActionRenameTarget] = useState<ActionRenameTarget | null>(null);
  const [actionRenameValue, setActionRenameValue] = useState("");
  const [actionRenameBusy, setActionRenameBusy] = useState(false);
  const [actionRenameError, setActionRenameError] = useState("");
  const [avatarRenameOpen, setAvatarRenameOpen] = useState(false);
  const [avatarRenameValue, setAvatarRenameValue] = useState("");
  const [avatarRenameBusy, setAvatarRenameBusy] = useState(false);
  const [avatarRenameError, setAvatarRenameError] = useState("");
  const [replacementError, setReplacementError] = useState("");
  const [replacementNotice, setReplacementNotice] = useState("");
  const [linkedPersonaName, setLinkedPersonaName] = useState<string | null>(null);
  const [personaChecked, setPersonaChecked] = useState(false);
  const replacementInput = useRef<HTMLInputElement>(null);
  const replacementTrigger = useRef<HTMLButtonElement>(null);
  const renameActionTrigger = useRef<HTMLButtonElement>(null);
  const renameAvatarTrigger = useRef<HTMLButtonElement>(null);
  const selectedInitialAction = useRef("");
  const currentDetailState = detailState.avatarId === avatarId
    ? detailState
    : { avatarId, status: "loading" as const, avatar: null };
  const avatar = currentDetailState.avatar;
  const loaded = currentDetailState.status === "loaded";

  useEffect(() => {
    const controller = new AbortController();
    setDetailState((current) => current.avatarId === avatarId
      ? { ...current, status: "loading" }
      : { avatarId, status: "loading", avatar: null });
    void fetchAvatarDetail(avatarId, controller.signal)
      .then((nextAvatar) => {
        if (controller.signal.aborted) return;
        setDetailState((current) => current.avatarId === avatarId
          ? { avatarId, status: "loaded", avatar: nextAvatar }
          : current);
        setActiveMediaIndex(nextAvatar?.actions.some(action => !action.deleted_at) ? 1 : 0);
        setAutoAdvancePinned(true);
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setDetailState((current) => current.avatarId === avatarId
          ? { avatarId, status: "loaded", avatar: null }
          : current);
      });
    return () => controller.abort();
  }, [avatarId]);

  useEffect(() => {
    const controller = new AbortController();
    setLinkedPersonaName(null);
    setPersonaChecked(false);
    void fetch(`/api/avatars/${encodeURIComponent(avatarId)}/persona`, { cache: "no-store", signal: controller.signal })
      .then((response) => readJsonResponse<{ profile?: AvatarPersonaProfile | null }>(response, "Persona 读取失败"))
      .then((payload) => {
        if (controller.signal.aborted) return;
        setLinkedPersonaName(payload.profile?.personaName ?? null);
        setPersonaChecked(true);
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setLinkedPersonaName(null);
        setPersonaChecked(true);
      });
    return () => controller.abort();
  }, [avatarId]);

  async function moveActiveActionToTrash() {
    if (
      !avatar
      || !activeAction
      || actionDeletionBusy
      || !avatar.canDeleteActions
      || !canDeleteAvatarAction(avatar.ownedActionIds, activeAction.avatar_action_id)
      || !window.confirm(`仅将当前动作“${activeAction.display_name}”移入回收站？数字人和其他动作不受影响，30 天内可以恢复。`)
    ) return;
    setActionDeletionBusy(true);
    setReplacementError("");
    setReplacementNotice("");
    try {
      const deletedAction = await updateOwnedAvatarAction(
        avatar.avatar_id,
        activeAction.avatar_action_id,
        { operation: "trash" },
      );
      setDetailState((current) => current.avatarId === avatarId && current.avatar
        ? {
            ...current,
            avatar: {
              ...current.avatar,
              actions: current.avatar.actions.map((action) => action.avatar_action_id === deletedAction.avatar_action_id
                ? deletedAction
                : action),
              ownedActionIds: current.avatar.ownedActionIds.filter((actionId) => actionId !== deletedAction.avatar_action_id),
            },
          }
        : current);
      setReadyStageActionId(null);
      setActiveMediaIndex(0);
      setAutoAdvancePinned(true);
      setReplacementNotice(`动作“${deletedAction.display_name}”已移入回收站`);
    } catch (error) {
      setReplacementError(error instanceof Error ? error.message : "Avatar 动作删除失败");
    } finally {
      setActionDeletionBusy(false);
    }
  }

  async function moveAvatarToTrash() {
    if (
      !avatar?.canDelete
      || avatarDeletionBusy
      || !window.confirm(`将整个数字人“${avatar.display_name}”移入回收站？其所有动作和口型对齐也会暂时不可用，30 天内可以恢复。`)
    ) return;
    setAvatarDeletionBusy(true);
    setReplacementError("");
    setReplacementNotice("");
    try {
      await setOwnedAvatarDeletion(avatar.avatar_id, true);
      window.location.assign(backHref);
    } catch (error) {
      setReplacementError(error instanceof Error ? error.message : "数字人资产删除失败");
      setAvatarDeletionBusy(false);
    }
  }

  function beginActionRename(action: OwnedAvatarActionRecord) {
    setAutoAdvancePinned(true);
    setActionRenameTarget({ avatarActionId: action.avatar_action_id, originalName: action.display_name });
    setActionRenameValue(action.display_name);
    setActionRenameError("");
    setReplacementError("");
    setReplacementNotice("");
  }

  function closeActionRename() {
    if (actionRenameBusy) return;
    setActionRenameTarget(null);
    setActionRenameError("");
    window.requestAnimationFrame(() => renameActionTrigger.current?.focus());
  }

  async function submitActionRename() {
    if (!avatar || !actionRenameTarget || actionRenameBusy) return;
    const displayName = actionRenameValue.trim();
    if (!displayName) {
      setActionRenameError("请填写动作名称");
      return;
    }
    if (displayName === actionRenameTarget.originalName) {
      closeActionRename();
      return;
    }
    setActionRenameBusy(true);
    setActionRenameError("");
    try {
      const renamedAction = await updateOwnedAvatarAction(
        avatar.avatar_id,
        actionRenameTarget.avatarActionId,
        { operation: "rename", displayName },
      );
      setDetailState((current) => current.avatarId === avatarId && current.avatar
        ? {
            ...current,
            avatar: {
              ...current.avatar,
              actions: current.avatar.actions.map((action) => action.avatar_action_id === renamedAction.avatar_action_id
                ? renamedAction
                : action),
            },
          }
        : current);
      setActionRenameTarget(null);
      setReplacementNotice(`动作已重命名为“${renamedAction.display_name}”`);
      window.requestAnimationFrame(() => renameActionTrigger.current?.focus());
    } catch (error) {
      setActionRenameError(error instanceof Error ? error.message : "动作名称修改失败");
    } finally {
      setActionRenameBusy(false);
    }
  }

  function beginAvatarRename() {
    if (!avatar?.canRename) return;
    setAutoAdvancePinned(true);
    setAvatarRenameValue(avatar.display_name);
    setAvatarRenameError("");
    setReplacementError("");
    setReplacementNotice("");
    setAvatarRenameOpen(true);
  }

  function closeAvatarRename() {
    if (avatarRenameBusy) return;
    setAvatarRenameOpen(false);
    setAvatarRenameError("");
    window.requestAnimationFrame(() => renameAvatarTrigger.current?.focus());
  }

  async function submitAvatarRename() {
    if (!avatar || !avatarRenameOpen || avatarRenameBusy) return;
    const displayName = avatarRenameValue.trim();
    if (!displayName) {
      setAvatarRenameError("请填写数字人名称");
      return;
    }
    if (displayName === avatar.display_name) {
      closeAvatarRename();
      return;
    }
    setAvatarRenameBusy(true);
    setAvatarRenameError("");
    try {
      const renamedAvatar = await renameOwnedAvatar(avatar.avatar_id, displayName);
      reconcileStoredAvatarDisplayConfig(renamedAvatar);
      setDetailState((current) => current.avatarId === avatarId && current.avatar
        ? {
            ...current,
            avatar: {
              ...current.avatar,
              display_name: renamedAvatar.display_name,
              updated_at: renamedAvatar.updated_at,
            },
          }
        : current);
      setAvatarRenameOpen(false);
      setReplacementNotice(`数字人已重命名为“${renamedAvatar.display_name}”`);
      window.requestAnimationFrame(() => renameAvatarTrigger.current?.focus());
    } catch (error) {
      setAvatarRenameError(error instanceof Error ? error.message : "数字人名称修改失败");
    } finally {
      setAvatarRenameBusy(false);
    }
  }

  async function prepareReplacement(file: File | undefined) {
    if (!file || replacementBusy) return;
    setReplacementError("");
    setReplacementNotice("");
    if (!new Set(["image/jpeg", "image/png", "image/webp"]).has(file.type)) {
      setReplacementError("仅支持 JPEG、PNG 或 WebP 形象图片");
      return;
    }
    if (!file.size || file.size > 8 * 1024 * 1024) {
      setReplacementError("形象图片不能为空且不能超过 8MB");
      return;
    }
    setReplacementBusy(true);
    try {
      const dataUrl = await normalizeAvatarSourceImage(await readFileAsDataUrl(file));
      setReplacementCandidate({ dataUrl, fileName: file.name });
      setTrashActionsOnReplace(true);
    } catch (error) {
      setReplacementError(error instanceof Error ? error.message : "形象图片处理失败");
    } finally {
      setReplacementBusy(false);
      if (replacementInput.current) replacementInput.current.value = "";
    }
  }

  async function confirmReplacement() {
    if (!avatar || !replacementCandidate || replacementBusy) return;
    const hadRealtimeBinding = Boolean(avatar.realtime_binding);
    const ownedActionIds = new Set(avatar.ownedActionIds);
    const activeActionCount = avatar.actions.filter((action) => ownedActionIds.has(action.avatar_action_id)).length;
    setReplacementBusy(true);
    setReplacementError("");
    try {
      const updated = await replaceOwnedAvatarSourceImage(avatar.avatar_id, {
        sourceImageDataUrl: replacementCandidate.dataUrl,
        trashActions: trashActionsOnReplace,
      });
      reconcileStoredAvatarDisplayConfig(updated);
      const activeOwnedActions = updated.actions.filter((action) => !action.deleted_at);
      setDetailState({
        avatarId,
        status: "loaded",
        avatar: {
          ...updated,
          actions: [
            ...avatar.actions.filter((action) => !ownedActionIds.has(action.avatar_action_id)),
            ...activeOwnedActions,
          ],
          canCreateActions: true,
          canRename: true,
          canDeleteActions: true,
          canDelete: true,
          ownedActionIds: activeOwnedActions.map((action) => action.avatar_action_id),
        },
      });
      setActiveMediaIndex(0);
      closeReplacementDialog();
      setReplacementNotice([
        "形象图片已更换",
        activeActionCount
          ? trashActionsOnReplace
            ? `${activeActionCount} 个旧动作已移入回收站`
            : `${activeActionCount} 个旧动作已保留`
          : "",
        hadRealtimeBinding ? "旧实时绑定已解除" : "",
      ].filter(Boolean).join("；"));
    } catch (error) {
      setReplacementError(error instanceof Error ? error.message : "形象图片更换失败");
    } finally {
      setReplacementBusy(false);
    }
  }

  function closeReplacementDialog() {
    setReplacementCandidate(null);
    setReplacementError("");
    window.requestAnimationFrame(() => replacementTrigger.current?.focus());
  }

  const actions = avatar?.actions.filter((action) => !action.deleted_at) ?? [];
  const activeAction = activeMediaIndex > 0 ? actions[activeMediaIndex - 1] ?? null : null;
  const selectedTalkingVariant = activeAction?.talking_variants?.find(
    variant => variant.id === selectedTalkingVariantId && !variant.deleted_at,
  ) ?? null;
  const canManageActiveAction = avatar && activeAction
    ? canDeleteAvatarAction(avatar.ownedActionIds, activeAction.avatar_action_id)
    : false;
  const canDeleteActiveAction = Boolean(avatar?.canDeleteActions && canManageActiveAction);
  const nextMediaIndex = actions.length ? (activeMediaIndex + 1) % (actions.length + 1) : 0;
  const avatarName = avatar?.display_name || "Avatar 详情";
  const avatarImageUrl = avatar
    ? `${avatar.source_image_url}?v=${encodeURIComponent(avatar.updated_at)}`
    : "";

  useEffect(() => {
    if (!avatar || !initialActionId) return;
    const selection = `${avatarId}:${initialActionId}`;
    if (selectedInitialAction.current === selection) return;
    const index = avatar.actions.filter(action => !action.deleted_at).findIndex(action => action.avatar_action_id === initialActionId);
    if (index < 0) return;
    selectedInitialAction.current = selection;
    setActiveMediaIndex(index + 1);
    setSelectedTalkingVariantId(null);
    setAutoAdvancePinned(true);
  }, [avatar, avatarId, initialActionId]);
  useEffect(() => {
    if (!initialActionId || activeAction?.avatar_action_id !== initialActionId || window.location.hash !== "#talking-materials") return;
    const frame = window.requestAnimationFrame(() => document.getElementById("talking-materials")?.scrollIntoView({ block: "start" }));
    return () => window.cancelAnimationFrame(frame);
  }, [activeAction?.avatar_action_id, initialActionId]);
  const conversationHref = activeAction
    ? `/conversation?avatar_id=${encodeURIComponent(avatarId)}&avatar_action_id=${encodeURIComponent(activeAction.avatar_action_id)}&experience=avatar`
    : `/conversation?avatar_id=${encodeURIComponent(avatarId)}&experience=avatar`;

  useEffect(() => {
    if (activeMediaIndex <= actions.length) return;
    setActiveMediaIndex(0);
  }, [actions.length, activeMediaIndex]);

  useEffect(() => {
    setReadyStageActionId(null);
    setSelectedTalkingVariantId(null);
  }, [avatarId]);

  useEffect(() => {
    const updateVisibility = () => setPageVisible(document.visibilityState === "visible");
    updateVisibility();
    document.addEventListener("visibilitychange", updateVisibility);
    return () => document.removeEventListener("visibilitychange", updateVisibility);
  }, []);

  useEffect(() => {
    if (!shouldAutoAdvanceAvatarDetailMedia({
      hasAvatar: Boolean(avatar),
      actionCount: actions.length,
      pageVisible,
      autoAdvancePinned,
      dockHovered,
      dockFocused,
      activeActionId: activeAction?.avatar_action_id ?? null,
      activeActionVideoUrl: activeAction?.video_url ?? null,
      readyStageActionId,
    })) return;
    const timer = window.setTimeout(() => {
      setReadyStageActionId(null);
      setActiveMediaIndex(nextMediaIndex);
    }, 3_000);
    return () => window.clearTimeout(timer);
  }, [actions.length, activeAction, autoAdvancePinned, avatar, dockFocused, dockHovered, nextMediaIndex, pageVisible, readyStageActionId]);

  function selectMedia(index: number) {
    setAutoAdvancePinned(true);
    if (index !== activeMediaIndex) {
      setReadyStageActionId(null);
      setSelectedTalkingVariantId(null);
    }
    setActiveMediaIndex(index);
  }

  if (loaded && !avatar) {
    return <section className={styles.missing}><h1>找不到这个 Avatar</h1><p>它可能已被删除，或只存在于其他账户。</p><BackLink href="/resources?tab=avatars" label="返回资产管理" /></section>;
  }

  return (
    <section className={styles.detail} aria-labelledby="avatar-detail-title">
      <section className={styles.stage} aria-label={`${avatarName} 媒体舞台`}>
        {avatar ? <Image className={styles.stageBackdrop} src={avatarImageUrl} alt="" aria-hidden="true" fill priority sizes="100vw" unoptimized /> : null}
        <div className={styles.stageMedia} data-kind={activeAction ? "action" : "image"}>
          {avatar && (selectedTalkingVariant?.video_url || activeAction?.video_url) ? (
            <video
              key={selectedTalkingVariant?.id ?? activeAction?.avatar_action_id}
              src={selectedTalkingVariant?.video_url ?? activeAction?.video_url ?? undefined}
              aria-label={selectedTalkingVariant
                ? `${avatar.display_name} · ${selectedTalkingVariant.display_name} 口型对齐`
                : `${avatar.display_name} · ${activeAction?.display_name}`}
              autoPlay
              muted
              loop
              playsInline
              controls
              preload="auto"
              poster={avatarImageUrl}
              onCanPlay={() => {
                setReadyStageActionId(activeAction?.avatar_action_id ?? null);
              }}
            />
          ) : avatar ? (
            <Image src={avatarImageUrl} alt={`${avatar.display_name} 形象`} fill priority sizes="(max-width: 800px) 100vw, 1100px" unoptimized />
          ) : null}
        </div>
        <span className={styles.stageScrim} aria-hidden="true" />

        <header className={styles.identity}>
          <div className={styles.identityMain}>
            <div className={styles.identityCopy}>
              <div className={styles.identityTitleRow}>
                <h1 id="avatar-detail-title">{avatarName}</h1>
                {avatar?.canRename ? <button
                  ref={renameAvatarTrigger}
                  className={styles.renameAvatar}
                  type="button"
                  aria-label={`修改数字人名称：${avatarName}`}
                  title="修改数字人名称"
                  disabled={avatarRenameBusy}
                  onClick={beginAvatarRename}
                ><Pencil /></button> : null}
                <span className={styles.actionCount}><Film />{actions.length ? `${actions.length} 个动作` : "尚未创建动作"}</span>
              </div>
              <AvatarPersonaStatus
                avatarId={avatarId}
                avatarName={avatarName}
                realtimeBound={Boolean(avatar?.realtime_binding)}
                linkedPersonaName={linkedPersonaName}
                personaChecked={personaChecked}
              />
            </div>

            <div className={styles.stageActions}>
              <Link className={styles.primaryAction} href={conversationHref} aria-label="开始对话">
                <MessageCircle />开始对话
              </Link>
              {avatarId.startsWith("avatar-personal-") ? <Link className={styles.secondaryAction} href={avatarDetailActionHref(`/services/motion?avatar_id=${encodeURIComponent(avatarId)}`, returnTo)}><Film />管理个人动作</Link> : null}
              {avatar?.canCreateActions !== false ? (
                <Link className={styles.secondaryAction} href={avatarDetailActionHref(`/avatars/create?task=action&avatar_id=${encodeURIComponent(avatarId)}`, returnTo)}>
                  <Film />创建动作
                </Link>
              ) : null}
              {avatar?.canCreateActions !== false ? <>
                <button ref={replacementTrigger} className={styles.replaceAction} type="button" disabled={replacementBusy} onClick={() => replacementInput.current?.click()}>
                  {replacementBusy ? <LoaderCircle className={styles.spin} /> : <ImagePlus />}更换图片
                </button>
                <input
                  ref={replacementInput}
                  className={styles.hiddenFileInput}
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  aria-label="选择新的 Avatar 形象图片"
                  onChange={(event) => void prepareReplacement(event.target.files?.[0])}
                />
              </> : null}
              {activeAction && canManageActiveAction ? <>
                <button
                  ref={renameActionTrigger}
                  className={styles.renameAction}
                  type="button"
                  aria-label={`修改动作名称：${activeAction.display_name}`}
                  title="修改当前动作名称"
                  disabled={actionRenameBusy}
                  onClick={() => beginActionRename(activeAction)}
                ><Pencil /></button>
              </> : null}
              {avatar?.canDelete || (activeAction && canDeleteActiveAction) ? <div className={styles.destructiveActions}>
                {activeAction && canDeleteActiveAction ? <button
                  className={styles.deleteAction}
                  type="button"
                  aria-label={`删除当前动作：${activeAction.display_name}`}
                  title={`仅删除当前动作：${activeAction.display_name}`}
                  disabled={actionDeletionBusy}
                  onClick={() => void moveActiveActionToTrash()}
                >{actionDeletionBusy ? <LoaderCircle className={styles.spin} /> : <Trash2 />}<span>删除当前动作</span></button> : null}
                {avatar?.canDelete ? <AvatarAssetDeleteButton
                  avatarName={avatar.display_name}
                  busy={avatarDeletionBusy}
                  onDelete={() => void moveAvatarToTrash()}
                /> : null}
              </div> : null}
            </div>
          </div>
        </header>

        {replacementError ? <p className={styles.replacementFeedback} data-kind="error" role="alert">{replacementError}</p> : null}
        {replacementNotice ? <p className={styles.replacementFeedback} data-kind="success" role="status"><Check />{replacementNotice}</p> : null}

        {activeAction ? <AvatarTalkingMaterialRail
          key={activeAction.avatar_action_id}
          placement="detail"
          avatarId={avatarId}
          action={activeAction}
          returnTo={returnTo}
          canManage={Boolean(canManageActiveAction)}
          canDelete={canDeleteActiveAction}
          canGenerate={Boolean(avatar?.canCreateActions)}
          selectedVariantId={selectedTalkingVariant?.id ?? null}
          onSelect={variantId => {
            setSelectedTalkingVariantId(variantId);
            setAutoAdvancePinned(true);
          }}
          onActionUpdated={updated => setDetailState(current => current.avatarId === avatarId && current.avatar
            ? { ...current, avatar: { ...current.avatar, actions: current.avatar.actions.map(item => item.avatar_action_id === updated.avatar_action_id ? updated : item) } }
            : current)}
        /> : null}

        <div
          className={styles.mediaDock}
          role="group"
          aria-label="形象和动作切换"
          data-auto-advance={autoAdvancePinned || dockHovered || dockFocused ? "paused" : "running"}
          onWheel={(event) => {
            if (event.currentTarget.scrollWidth <= event.currentTarget.clientWidth) return;
            const delta = getAvatarActionDockWheelDelta(event.deltaX, event.deltaY);
            if (!delta) return;
            event.preventDefault();
            event.currentTarget.scrollLeft += delta;
          }}
          onPointerEnter={() => setDockHovered(true)}
          onPointerLeave={() => {
            setDockHovered(false);
            setPreviewMediaIndex(null);
          }}
          onFocusCapture={() => setDockFocused(true)}
          onBlurCapture={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
              setDockFocused(false);
              setPreviewMediaIndex(null);
            }
          }}
        >
          <button
            type="button"
            data-current={activeMediaIndex === 0}
            aria-current={activeMediaIndex === 0 ? "true" : undefined}
            aria-label={`查看形象：${avatarName}`}
            onPointerEnter={() => setPreviewMediaIndex(0)}
            onFocus={() => setPreviewMediaIndex(0)}
            onClick={() => selectMedia(0)}
          >
            <span className={styles.dockMedia}>{avatar ? <Image src={avatarImageUrl} alt="" fill sizes="100px" unoptimized /> : <ImageIcon />}</span>
            <small>形象</small>
            <strong>{avatarName}</strong>
          </button>
          {actions.map((action, index) => (
            <button
              key={action.avatar_action_id}
              type="button"
              data-current={activeMediaIndex === index + 1}
              aria-current={activeMediaIndex === index + 1 ? "true" : undefined}
              aria-label={`查看动作：${action.display_name}`}
              onPointerEnter={() => setPreviewMediaIndex(index + 1)}
              onFocus={() => setPreviewMediaIndex(index + 1)}
              onClick={() => selectMedia(index + 1)}
            >
              <span className={styles.dockMedia}>
                {action.video_url ? <ActionDockPreview
                  src={action.video_url}
                  poster={avatarImageUrl}
                  label={`${avatarName} · ${action.display_name} 缩略预览`}
                  playing={activeMediaIndex === index + 1 || previewMediaIndex === index + 1}
                  pageVisible={pageVisible}
                  startDelayMs={(index % 6) * 90}
                /> : avatar ? <Image src={avatarImageUrl} alt="" fill sizes="100px" unoptimized /> : <Film />}
              </span>
              <small>动作 {index + 1}</small>
              <strong>{action.display_name}</strong>
            </button>
          ))}
          {avatar?.canCreateActions !== false ? (
            <Link className={styles.addMedia} href={avatarDetailActionHref(`/avatars/create?task=action&avatar_id=${encodeURIComponent(avatarId)}`, returnTo)} aria-label="创建新的 Avatar 动作">
              <Film /><span>新增动作</span>
            </Link>
          ) : null}
        </div>
      </section>

      <details className={styles.technical}>
        <summary>
          <span><Radio />技术信息</span>
          <div><em>图片可直接使用</em><em>{actions.length ? `${actions.length} 个动作` : "尚未创建动作"}</em></div>
          <ChevronDown />
        </summary>
        <div className={styles.technicalGrid}>
          <article><span>Avatar ID</span><code>{avatarId}</code></article>
          <article><span>实时驱动</span><strong>{avatar?.realtime_binding ? "Anam 已连接" : avatar?.canCreateActions === false ? "供应商托管" : "未创建，可直接使用图片"}</strong></article>
          <article><span>动作资产</span><strong>{actions.length ? `${actions.length} 个可选动作` : avatar?.canCreateActions === false ? "实时驱动无需动作" : "尚未创建动作"}</strong></article>
          {avatar?.realtime_binding ? <article><span>Provider / Model</span><code>{avatar.realtime_binding.provider_avatar_id} · {avatar.realtime_binding.avatar_model}</code></article> : null}
        </div>
      </details>

      {actionRenameTarget ? <AvatarActionRenameDialog
        actionName={actionRenameTarget.originalName}
        value={actionRenameValue}
        busy={actionRenameBusy}
        error={actionRenameError}
        onValueChange={setActionRenameValue}
        onCancel={closeActionRename}
        onSubmit={() => void submitActionRename()}
      /> : null}

      {avatar && avatarRenameOpen ? <AvatarActionRenameDialog
        assetKind="avatar"
        actionName={avatar.display_name}
        value={avatarRenameValue}
        busy={avatarRenameBusy}
        error={avatarRenameError}
        onValueChange={setAvatarRenameValue}
        onCancel={closeAvatarRename}
        onSubmit={() => void submitAvatarRename()}
      /> : null}

      {avatar && replacementCandidate ? (
        <AvatarSourceReplacementDialog
          avatarName={avatar.display_name}
          fileName={replacementCandidate.fileName}
          previewImageUrl={replacementCandidate.dataUrl}
          actionCount={actions.length}
          hasRealtimeBinding={Boolean(avatar.realtime_binding)}
          trashActions={trashActionsOnReplace}
          busy={replacementBusy}
          error={replacementError}
          onTrashActionsChange={setTrashActionsOnReplace}
          onCancel={() => { if (!replacementBusy) closeReplacementDialog(); }}
          onConfirm={() => void confirmReplacement()}
        />
      ) : null}
    </section>
  );
}

function reconcileStoredAvatarDisplayConfig(avatar: OwnedAvatarRecord) {
  try {
    const stored = parseAvatarDisplayConfig(JSON.parse(
      window.localStorage.getItem(AVATAR_DISPLAY_CONFIG_STORAGE_KEY) ?? "null",
    ));
    const reconciled = reconcileAvatarDisplayConfigWithOwnedAvatar(stored, avatar);
    if (reconciled !== stored) {
      window.localStorage.setItem(AVATAR_DISPLAY_CONFIG_STORAGE_KEY, JSON.stringify(reconciled));
    }
  } catch {
    // Session startup performs the same reconciliation before using persisted config.
  }
}

export function AvatarSourceReplacementDialog({
  avatarName,
  fileName,
  previewImageUrl,
  actionCount,
  hasRealtimeBinding,
  trashActions,
  busy,
  error,
  onTrashActionsChange,
  onCancel,
  onConfirm,
}: {
  avatarName: string;
  fileName: string;
  previewImageUrl: string;
  actionCount: number;
  hasRealtimeBinding: boolean;
  trashActions: boolean;
  busy: boolean;
  error: string;
  onTrashActionsChange: (checked: boolean) => void;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const dialog = useRef<HTMLElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const busyRef = useRef(busy);
  const onCancelRef = useRef(onCancel);

  useEffect(() => {
    busyRef.current = busy;
    onCancelRef.current = onCancel;
  });

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButton.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (!busyRef.current) {
          event.preventDefault();
          onCancelRef.current();
        }
        return;
      }
      if (event.key !== "Tab" || !dialog.current) return;
      const focusable = Array.from(dialog.current.querySelectorAll<HTMLElement>(
        "button:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex='-1'])",
      ));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, []);

  return (
    <div className={styles.replacementBackdrop} role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget && !busy) onCancel();
    }}>
      <section ref={dialog} className={styles.replacementDialog} role="dialog" aria-modal="true" aria-labelledby="replace-avatar-image-title" aria-describedby="replace-avatar-image-description">
        <header>
          <span><ImagePlus /></span>
          <div><h2 id="replace-avatar-image-title">更换“{avatarName}”的形象图片？</h2></div>
          <button ref={closeButton} type="button" aria-label="取消更换形象图片" disabled={busy} onClick={onCancel}><X /></button>
        </header>
        <div className={styles.replacementPreview}>
          <span><Image src={previewImageUrl} alt="新形象图片预览" fill sizes="120px" unoptimized /></span>
          <div><small>新图片</small><strong>{fileName}</strong><p id="replace-avatar-image-description">Avatar 名称和 ID 将保持不变。</p></div>
        </div>
        {hasRealtimeBinding ? (
          <div className={styles.replacementWarning}>
            <AlertTriangle />
            <p><strong>实时绑定将自动解除</strong><span>当前绑定由旧图片创建。替换后需要重新创建并确认实时形象；Anam 远端形象不会被删除。</span></p>
          </div>
        ) : null}
        {actionCount ? (
          <label className={styles.replacementChoice}>
            <input type="checkbox" checked={trashActions} disabled={busy} onChange={(event) => onTrashActionsChange(event.target.checked)} />
            <span><Check /></span>
            <p><strong>将 {actionCount} 个旧动作移入回收站</strong><small>取消勾选可保留动作，但动作画面仍会是旧人物。</small></p>
          </label>
        ) : <p className={styles.replacementNoActions}>当前没有旧动作需要处理。</p>}
        {error ? <p className={styles.replacementDialogError} role="alert">{error}</p> : null}
        <footer>
          <button type="button" disabled={busy} onClick={onCancel}>取消</button>
          <button type="button" disabled={busy} onClick={onConfirm}>{busy ? <LoaderCircle className={styles.spin} /> : <ImagePlus />}确认更换</button>
        </footer>
      </section>
    </div>
  );
}

async function fetchAvatarDetail(avatarId: string, signal: AbortSignal): Promise<AvatarDetailRecord | null> {
  const [ownedResult, catalogResult] = await Promise.allSettled([
    fetchOwnedAvatar(avatarId, signal),
    loadCurrentAvatarCatalog(signal, {
      includeHostedAvatars: avatarId.startsWith("anam-"),
      includeOwnedBuiltinActions: true,
    }),
  ]);
  if (signal.aborted) throw new DOMException("Avatar detail request aborted", "AbortError");

  const ownedAvatar = ownedResult.status === "fulfilled" ? ownedResult.value : null;
  const catalogAvatar = catalogResult.status === "fulfilled"
    ? catalogResult.value.find((candidate) => candidate.avatarId === avatarId) ?? null
    : null;
  if (!ownedAvatar && !catalogAvatar) {
    if (ownedResult.status === "rejected") throw ownedResult.reason;
    return null;
  }

  const activeOwnedActions = ownedAvatar?.actions.filter((action) => !action.deleted_at) ?? [];
  const ownedActionsById = new Map(activeOwnedActions.map((action) => [action.avatar_action_id, action]));
  const timestamp = ownedAvatar?.updated_at ?? new Date(0).toISOString();
  const catalogActions: OwnedAvatarActionRecord[] = catalogAvatar
    ? catalogAvatar.actions.map((action) => ownedActionsById.get(action.avatarActionId) ?? ({
      avatar_action_id: action.avatarActionId,
      display_name: action.displayName,
      video_url: action.videoUrl,
      pending_model_count: action.pendingModelCount,
      created_at: timestamp,
      deleted_at: null,
    }))
    : [];
  const catalogActionIds = new Set(catalogActions.map((action) => action.avatar_action_id));
  const actions = dedupeAvatarActionsByDisplayName([
    ...catalogActions,
    ...activeOwnedActions.filter((action) => !catalogActionIds.has(action.avatar_action_id)),
  ]);
  const realtimeBinding = ownedAvatar?.realtime_binding ?? (catalogAvatar?.realtimeBinding ? {
    avatar_id: avatarId,
    provider_avatar_id: catalogAvatar.realtimeBinding.providerAvatarId,
    provider: catalogAvatar.realtimeBinding.provider,
    avatar_model: catalogAvatar.realtimeBinding.avatarModel,
    state: "accepted" as const,
    preview_video_url: catalogAvatar.realtimeBinding.previewVideoUrl,
  } : null);
  return {
    avatar_id: avatarId,
    display_name: ownedAvatar?.display_name ?? catalogAvatar!.displayName,
    source_image_url: ownedAvatar?.source_image_url ?? catalogAvatar!.source.imageUrl,
    created_at: ownedAvatar?.created_at ?? timestamp,
    updated_at: timestamp,
    deleted_at: ownedAvatar?.deleted_at ?? catalogAvatar!.deletedAt,
    realtime_binding: realtimeBinding,
    actions,
    canCreateActions: !avatarId.startsWith("avatar-personal-") && (Boolean(ownedAvatar) || Boolean(catalogAvatar?.canCreateActions)),
    canRename: Boolean(ownedAvatar),
    canDeleteActions: !avatarId.startsWith("avatar-personal-"),
    canDelete: !avatarId.startsWith("avatar-personal-") && Boolean(ownedAvatar),
    ownedActionIds: activeOwnedActions.map((action) => action.avatar_action_id),
  };
}

function readFileAsDataUrl(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("形象图片读取失败"));
    reader.onload = () => typeof reader.result === "string"
      ? resolve(reader.result)
      : reject(new Error("形象图片读取失败"));
    reader.readAsDataURL(file);
  });
}

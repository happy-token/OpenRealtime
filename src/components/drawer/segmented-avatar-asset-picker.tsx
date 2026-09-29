"use client";
import { useLanguage } from "@/components/language/language-provider";


import Image from "next/image";
import Link from "next/link";
import { Check, ChevronLeft, ChevronRight, Minimize2, MoreHorizontal } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { AvatarMediaCoverflow, avatarImageMediaId } from "@/components/avatar/avatar-media-coverflow";
import type { AvatarAction, AvatarAsset } from "@/lib/avatar-catalog";
import { isSegmentedAvatarAsset } from "@/lib/avatar-library-catalog-client";

function isPlayableAvatarAction(action: AvatarAction) {
  return action.state === "available" && !action.pendingModelCount;
}

export function shouldAutoAdvanceSegmentedAvatarCardMedia({
  focused,
  active,
  menuOpen,
  manuallyPaused,
  selected,
  playableActionCount,
}: {
  focused: boolean;
  active: boolean;
  menuOpen: boolean;
  manuallyPaused: boolean;
  selected: boolean;
  playableActionCount: number;
}) {
  return active && !focused && !menuOpen && !manuallyPaused && !selected && playableActionCount > 0;
}

export function filterSegmentedAvatarAssets(avatars: AvatarAsset[]) {
  return avatars.filter((avatar) => (
    avatar.source.kind === "owned" && isSegmentedAvatarAsset(avatar)
  ));
}

export function SegmentedAvatarAssetPicker({
  avatars,
  selectedAvatarId,
  selectedActionId,
  disabled,
  active,
  showCollapsedSummary = true,
  ariaLabel = "多段式 Avatar 资产",
  actionsOnly = false,
  selectedPreviewUrl,
  selectedPreviewControls,
  onSelect,
}: {
  avatars: AvatarAsset[];
  selectedAvatarId: string;
  selectedActionId: string;
  disabled: boolean;
  active: boolean;
  showCollapsedSummary?: boolean;
  ariaLabel?: string;
  actionsOnly?: boolean;
  selectedPreviewUrl?: string;
  selectedPreviewControls?: ReactNode;
  onSelect: (avatar: AvatarAsset, action: AvatarAction | null) => void;
}) {
  const { t } = useLanguage();
  const segmentedAvatars = useMemo(() => actionsOnly
    ? avatars.filter(avatar => avatar.source.kind === "owned" && !avatar.deletedAt && avatar.actions.length > 0)
    : filterSegmentedAvatarAssets(avatars), [avatars, actionsOnly]);
  const [focusedAvatarId, setFocusedAvatarId] = useState<string | null>(null);

  useEffect(() => {
    if (!focusedAvatarId || segmentedAvatars.some((avatar) => avatar.avatarId === focusedAvatarId)) return;
    setFocusedAvatarId(null);
  }, [focusedAvatarId, segmentedAvatars]);

  return (
    <section className="segmented-avatar-picker" aria-label={ariaLabel} data-focus-active={Boolean(focusedAvatarId)}>
      {focusedAvatarId || showCollapsedSummary ? (
        <div className="segmented-avatar-picker-summary">
          <strong>{focusedAvatarId ? t("形象与动作") : t("内置 Avatar")}</strong>
          <span>{focusedAvatarId ? t("使用左右按钮切换预览") : "" + (segmentedAvatars.length) + t(" 个形象")}</span>
        </div>
      ) : null}
      <div className="segmented-avatar-picker-grid">
        {segmentedAvatars.map((avatar) => (
          <SegmentedAvatarCard
            key={avatar.avatarId}
            avatar={avatar}
            actionsOnly={actionsOnly}
            selectedPreviewUrl={selectedPreviewUrl}
            selectedPreviewControls={selectedPreviewControls}
            focused={focusedAvatarId === avatar.avatarId}
            selectedAvatarId={selectedAvatarId}
            selectedActionId={selectedActionId}
            disabled={disabled}
            active={active}
            onFocus={() => setFocusedAvatarId(avatar.avatarId)}
            onCloseFocus={() => setFocusedAvatarId(null)}
            onSelect={onSelect}
          />
        ))}
        {segmentedAvatars.length === 0 ? <p className="segmented-avatar-picker-empty">{t("暂无可用 Avatar")}</p> : null}
      </div>
    </section>
  );
}

function SegmentedAvatarCard({
  avatar,
  actionsOnly,
  selectedPreviewUrl,
  selectedPreviewControls,
  focused,
  selectedAvatarId,
  selectedActionId,
  disabled,
  active,
  onFocus,
  onCloseFocus,
  onSelect,
}: {
  avatar: AvatarAsset;
  actionsOnly: boolean;
  selectedPreviewUrl?: string;
  selectedPreviewControls?: ReactNode;
  focused: boolean;
  selectedAvatarId: string;
  selectedActionId: string;
  disabled: boolean;
  active: boolean;
  onFocus: () => void;
  onCloseFocus: () => void;
  onSelect: (avatar: AvatarAsset, action: AvatarAction | null) => void;
}) {
  const { t } = useLanguage();
  const actions = useMemo(() => avatar.actions, [avatar.actions]);
  const playableActions = useMemo(
    () => actions.filter((action) => isPlayableAvatarAction(action) && Boolean(action.videoUrl)),
    [actions],
  );
  const selectedIndex = selectedAvatarId === avatar.avatarId
    ? Math.max(actionsOnly ? 1 : 0, avatar.actions.findIndex((action) => action.avatarActionId === selectedActionId) + 1)
    : actionsOnly ? 1 : 0;
  const [mediaIndex, setMediaIndex] = useState(selectedIndex);
  const [menuOpen, setMenuOpen] = useState(false);
  const [manuallyPaused, setManuallyPaused] = useState(false);
  const cardRef = useRef<HTMLElement>(null);
  const mediaCount = actions.length + 1;
  const action = mediaIndex > 0 ? actions[mediaIndex - 1] ?? null : null;
  const imageSelectionId = `builtin:identity-static:${avatar.avatarId}`;
  const selected = selectedAvatarId === avatar.avatarId && (action
    ? selectedActionId === action.avatarActionId
    : !selectedActionId || selectedActionId === imageSelectionId);
  const avatarSelected = selectedAvatarId === avatar.avatarId;
  const selectionLabel = action ? `确认使用${actionsOnly ? "口型对齐" : "动作"}：${action.displayName}` : `确认使用形象：${avatar.displayName}`;
  const configuredMediaId = selectedAvatarId === avatar.avatarId && selectedActionId && selectedActionId !== imageSelectionId
    ? selectedActionId
    : selectedAvatarId === avatar.avatarId ? avatarImageMediaId(avatar.avatarId) : undefined;

  useEffect(() => {
    if (selectedAvatarId !== avatar.avatarId) return;
    const nextIndex = avatar.actions.findIndex((candidate) => candidate.avatarActionId === selectedActionId) + 1;
    setMediaIndex(Math.max(actionsOnly ? 1 : 0, nextIndex));
  }, [avatar.actions, avatar.avatarId, selectedActionId, selectedAvatarId, actionsOnly]);

  useEffect(() => {
    if (mediaIndex < mediaCount) return;
    setMediaIndex(actionsOnly ? 1 : 0);
  }, [mediaCount, mediaIndex, actionsOnly]);

  useEffect(() => {
    if (!shouldAutoAdvanceSegmentedAvatarCardMedia({
      focused,
      active,
      menuOpen,
      manuallyPaused,
      selected: avatarSelected,
      playableActionCount: playableActions.length,
    })) return;
    const timer = window.setTimeout(() => {
      setMediaIndex((current) => actionsOnly ? (current % actions.length) + 1 : (current + 1) % mediaCount);
    }, 3_000);
    return () => window.clearTimeout(timer);
  }, [playableActions.length, active, avatarSelected, focused, manuallyPaused, mediaCount, menuOpen, mediaIndex, actionsOnly, actions.length]);

  useEffect(() => {
    if (!menuOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [menuOpen]);

  useEffect(() => {
    if (!focused) return;
    const frame = window.requestAnimationFrame(() => cardRef.current?.scrollIntoView({ block: "nearest", behavior: "auto" }));
    return () => window.cancelAnimationFrame(frame);
  }, [focused]);

  return (
    <article
      ref={cardRef}
      className="segmented-avatar-card"
      aria-label={"" + (avatar.displayName) + t(" 形象与动作")}
      data-selected={selected}
      data-avatar-selected={avatarSelected}
      data-focused={focused}
      data-preview-kind={action ? "action" : "image"}
      data-actions-only={actionsOnly}
    >
      {focused && !actionsOnly ? (
          <AvatarMediaCoverflow
            avatarId={avatar.avatarId}
            avatarName={avatar.displayName}
            imageUrl={avatar.source.imageUrl}
            actions={actions}
            filterPlayableActions={false}
            activeIndex={mediaIndex}
            active={active}
            selectedMediaId={configuredMediaId}
            onActiveIndexChange={setMediaIndex}
          />
        ) : (
          <div className="segmented-avatar-card-media" data-has-actions={avatar.actions.length > 0}>
          <div className="segmented-avatar-card-stage">
            {active && action?.videoUrl ? (
              <>
                <Image className="segmented-avatar-card-backdrop" src={avatar.source.imageUrl} alt="" aria-hidden="true" fill sizes="(max-width: 700px) 100vw, 260px" unoptimized />
                <video className="segmented-avatar-card-action-video" key={selected && selectedPreviewUrl ? selectedPreviewUrl : action.avatarActionId} src={selected && selectedPreviewUrl ? selectedPreviewUrl : action.videoUrl} poster={avatar.source.imageUrl} aria-label={`${avatar.displayName} · ${action.displayName}`} autoPlay={active} muted loop playsInline preload="auto" />
              </>
            ) : (
              <>
                <Image className="segmented-avatar-card-backdrop" src={avatar.source.imageUrl} alt="" aria-hidden="true" fill sizes="(max-width: 700px) 100vw, 260px" unoptimized />
                <Image className="segmented-avatar-card-portrait" src={avatar.source.imageUrl} alt={"" + (avatar.displayName) + t(" 形象")} fill sizes="(max-width: 700px) 100vw, 260px" unoptimized />
              </>
            )}
          </div>
          <button className="segmented-avatar-card-expand" type="button" aria-label={t("展开 ") + (avatar.displayName) + t(" 的形象和动作")} onClick={onFocus} />
          {mediaCount > 1 ? (
            <div className="segmented-avatar-card-media-navigation" aria-label={"" + (avatar.displayName) + t(" 形象与动作切换")}>
              <button
                type="button"
                aria-label={t("上一项：") + (avatar.displayName) + ""}
                onClick={() => {
                  setManuallyPaused(true);
                  setMediaIndex((current) => actionsOnly ? ((current - 2 + actions.length) % actions.length) + 1 : (current - 1 + mediaCount) % mediaCount);
                }}
              >
                <ChevronLeft aria-hidden="true" />
              </button>
              <button
                type="button"
                aria-label={t("下一项：") + (avatar.displayName) + ""}
                onClick={() => {
                  setManuallyPaused(true);
                  setMediaIndex((current) => actionsOnly ? (current % actions.length) + 1 : (current + 1) % mediaCount);
                }}
              >
                <ChevronRight aria-hidden="true" />
              </button>
            </div>
          ) : null}
          <button
            className="segmented-avatar-card-quick-use"
            type="button"
            data-selected={selected}
            disabled={disabled || selected}
            aria-label={selected ? t("当前使用：") + (action?.displayName ?? avatar.displayName) + "" : selectionLabel}
            onClick={() => onSelect(avatar, action)}
          >
            {selected ? <><Check aria-hidden="true" />{t("当前使用")}</> : t("确认使用")}
          </button>
          {selected && selectedPreviewControls ? selectedPreviewControls : null}
          {avatarSelected && !selectedPreviewControls ? <span className="segmented-avatar-card-selected"><Check />{t("当前 Avatar")}</span> : null}
          <button style={selected && selectedPreviewControls ? { top: 48 } : undefined} className="segmented-avatar-card-action-count" type="button" aria-label={t("浏览 ") + (avatar.displayName) + t(" 的形象与动作")} onClick={onFocus}>
            {avatar.actions.length ? "" + (avatar.actions.length) + t(" 个") + (actionsOnly ? "口型对齐" : "动作") + "" : t("未创建动作")}
          </button>
        </div>
      )}

      {focused ? (
        <div className="segmented-avatar-card-body segmented-avatar-card-confirmation">
          <button className="segmented-avatar-card-use" type="button" data-selected={selected} disabled={disabled || selected} onClick={() => onSelect(avatar, action)}>
            {selected ? <><Check />{t("当前使用")}</> : selectionLabel}
          </button>
          <button className="segmented-avatar-card-close-preview" type="button" aria-label={t("收起 ") + (avatar.displayName) + t(" 动作选择")} title={t("收起预览")} onClick={onCloseFocus}><Minimize2 /></button>
        </div>
      ) : (
        <div className="segmented-avatar-card-body">
          <div className="segmented-avatar-card-title">
            <span>
              <strong>{avatar.displayName}</strong>
              <em>{action
                ? "" + (actionsOnly ? "口型对齐" : action.state === "available" && !action.pendingModelCount ? "动作" : "待适配动作") + " · " + (action.displayName) + ""
                : t("形象预览")}</em>
            </span>
            <button className="segmented-avatar-card-more" type="button" aria-label={t("更多操作：") + (avatar.displayName) + ""} aria-expanded={menuOpen} onClick={() => setMenuOpen((open) => !open)}>
              <MoreHorizontal />
            </button>
          </div>
          <div className="segmented-avatar-card-menu" aria-label={"" + (avatar.displayName) + t(" 操作菜单")} hidden={!menuOpen}>
            <button type="button" onClick={() => { setMenuOpen(false); onFocus(); }}>{t("查看形象与动作")}</button>
            <Link href="/resources?tab=avatars&scope=internal-preset" onClick={() => setMenuOpen(false)}>{t("数字人资产管理")}</Link>
          </div>
        </div>
      )}
    </article>
  );
}

"use client";

import { useEffect, useRef, useState, useSyncExternalStore, type SyntheticEvent } from "react";
import Link from "next/link";
import { LoaderCircle, RotateCcw } from "lucide-react";
import { getPlaybackActive, getServerPlaybackActive, subscribePlaybackActivity } from "@/voice/audio/playback-activity";
import { fetchOwnedAvatar, fetchOwnedAvatars, fetchPersonalAvatars } from "@/lib/avatar-catalog-client";
import type { OwnedAvatarRecord } from "@/lib/avatar-records";
import { SegmentedAvatarAssetPicker } from "@/components/drawer/segmented-avatar-asset-picker";
import type { AvatarAsset } from "@/lib/avatar-catalog";
import styles from "@/components/call/preview-workspace-lab.module.css";
import type { AvatarDisplayConfig } from "./types";
import { sampleMediaAmbientColor } from "@/lib/ambient-color";

export function shouldShowTalkingMotion(
  audioActive: boolean,
  degraded = false,
): boolean {
  return audioActive && !degraded;
}

export function resolveMotionPair(avatar: OwnedAvatarRecord | null, config: AvatarDisplayConfig) {
  if (!avatar || avatar.deleted_at || avatar.avatar_id !== config.segmentedAvatarId) return null;
  const idle = avatar.actions.find(a => a.avatar_action_id === config.segmentedAvatarActionId && !a.deleted_at && a.video_url);
  const talking = idle?.talking_variants?.find(v => v.id === config.motionTalkingVariantId && !v.deleted_at && v.source_video_url === idle.video_url);
  return idle?.video_url && talking ? { idle: idle.video_url, talking: talking.video_url } : null;
}

export function filterPairedMotionCatalog(catalog: AvatarAsset[], owned: OwnedAvatarRecord[]): AvatarAsset[] {
  return catalog.flatMap(asset => {
    const avatar = owned.find(item => item.avatar_id === asset.avatarId && !item.deleted_at);
    if (!avatar || asset.deletedAt) return [];
    const actions = asset.actions.filter(action => {
      const source = avatar.actions.find(item => item.avatar_action_id === action.avatarActionId && !item.deleted_at);
      return action.state === "available" && !action.pendingModelCount && Boolean(source?.video_url && source.video_url === action.videoUrl && source.talking_variants?.some(variant => !variant.deleted_at && variant.source_video_url === source.video_url && variant.video_url));
    });
    return actions.length ? [{ ...asset, actions }] : [];
  });
}

/** Adapt paired clips to the existing media picker; IDs here identify variants, not base actions. */
export function buildTalkingMaterialCatalog(catalog: AvatarAsset[], owned: OwnedAvatarRecord[]): AvatarAsset[] {
  return catalog.flatMap(asset => {
    const avatar = owned.find(item => item.avatar_id === asset.avatarId && !item.deleted_at);
    if (!avatar || asset.deletedAt) return [];
    const actions = avatar.actions.flatMap(base => {
      if (base.deleted_at || !base.video_url) return [];
      return (base.talking_variants ?? []).filter(v => !v.deleted_at && v.source_video_url === base.video_url && v.video_url).map(v => ({
        avatarActionId: v.id, displayName: `${base.display_name} · ${v.method === "lipforcing" ? "Lip Forcing" : v.method === "musetalk" ? "MuseTalk" : v.method === "minimax" ? "MiniMax" : "Wav2Lip"}`,
        videoUrl: v.video_url, state: "available" as const, pendingModelCount: 0,
      }));
    });
    return actions.length ? [{ ...asset, actions }] : [];
  });
}

export function MotionOrchestrationConfig({ config, onChange, catalog, active = true }: { config: AvatarDisplayConfig; onChange: (value: AvatarDisplayConfig) => void; catalog: AvatarAsset[]; active?: boolean }) {
  const [avatars, setAvatars] = useState<OwnedAvatarRecord[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    void Promise.all([fetchOwnedAvatars(controller.signal).catch(() => []), fetchPersonalAvatars(controller.signal)])
      .then(([shared, personal]) => { setAvatars([...shared, ...personal]); setError(""); })
      .catch(e => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "资产读取失败"); });
    return () => controller.abort();
  }, [active, catalog]);
  const materials = buildTalkingMaterialCatalog(catalog, avatars);
  return <section aria-label="动作编排配置" className={styles.motionOrchestrationConfig}>
    <div className={styles.segmentedAvatarAssets}>
      <div className={styles.segmentedAvatarAssetsHeader}>
        <span><strong>口型对齐</strong></span>
        {!config.segmentedAvatarId.startsWith("avatar-personal-") ? <Link href={`/avatars/create?task=lightweight${config.segmentedAvatarId ? `&avatar_id=${encodeURIComponent(config.segmentedAvatarId)}` : ""}`}>生成口型对齐</Link> : null}
      </div>
      <SegmentedAvatarAssetPicker actionsOnly avatars={materials} selectedAvatarId={config.segmentedAvatarId} selectedActionId={config.motionTalkingVariantId ?? ""} disabled={false} active={active} showCollapsedSummary={false} ariaLabel="动作编排口型对齐" onSelect={(next, material) => {
        const avatar = avatars.find(a => a.avatar_id === next.avatarId && !a.deleted_at);
        const base = avatar?.actions.find(a => !a.deleted_at && a.video_url && a.talking_variants?.some(v => v.id === material?.avatarActionId && !v.deleted_at && v.source_video_url === a.video_url));
        if (!base || !material) return;
        onChange({ ...config, segmentedAvatarId: next.avatarId, segmentedDisplayName: next.displayName, segmentedAvatarActionId: base.avatar_action_id, motionTalkingVariantId: material.avatarActionId });
      }} />
      <p>选择口型对齐即可，待机时自动播放对应的原动作。</p>
    </div>
    {error && <p role="alert">{error}</p>}
  </section>;

}

export function MotionOrchestrationStage({ config, onReady, caption, statusLabel, onAmbientColorChange }: { config: AvatarDisplayConfig; onReady?: () => void; caption?: string; statusLabel?: string; onAmbientColorChange?: (color: string | null) => void }) {
  const audioActive = useSyncExternalStore(subscribePlaybackActivity, getPlaybackActive, getServerPlaybackActive);
  const [degraded, setDegraded] = useState(false);
  const showingTalking = shouldShowTalkingMotion(audioActive, degraded);
  const [pair, setPair] = useState<{ idle: string; talking: string } | null>(null);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(0);
  const [connectionAttempt, setConnectionAttempt] = useState(0);
  const [showStartupFallback, setShowStartupFallback] = useState(false);
  const idleRef = useRef<HTMLVideoElement>(null);
  const talkingRef = useRef<HTMLVideoElement>(null);
  const readyRef = useRef(onReady);
  const readyReported = useRef(false);
  const reportedAmbientColor = useRef<string | null>(null);
  readyRef.current = onReady;
  useEffect(() => {
    if (degraded) return;
    const controller = new AbortController();
    readyReported.current = false;
    setPair(null); setError(""); setLoaded(0);
    void fetchOwnedAvatar(config.segmentedAvatarId, controller.signal).then(avatar => {
      if (controller.signal.aborted) return;
      const next = resolveMotionPair(avatar, config);
      if (!next) throw new Error("动作配对不可用，请返回工作台重新选择素材。");
      setPair(next);
    }).catch(e => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "素材读取失败"); });
    return () => controller.abort();
  }, [config, connectionAttempt, degraded]);
  useEffect(() => {
    if (!pair || degraded) return;
    let active = true;
    const timer = window.setInterval(() => {
      void fetchOwnedAvatar(config.segmentedAvatarId).then(avatar => {
        if (!active) return;
        if (resolveMotionPair(avatar, config)) return;
        setPair(null);
        setError("口型对齐已从资产管理移除，请重新选择素材。");
      }).catch(() => {
        // A transient catalog failure must not interrupt an already playing session.
      });
    }, 10_000);
    return () => { active = false; window.clearInterval(timer); };
  }, [config, degraded, pair]);
  useEffect(() => {
    if (readyReported.current || (!degraded && (loaded !== 3 || error))) return;
    readyReported.current = true;
    readyRef.current?.();
  }, [degraded, loaded, error]);
  useEffect(() => {
    if (degraded || error || loaded === 3) {
      setShowStartupFallback(false);
      return;
    }
    const timer = window.setTimeout(() => setShowStartupFallback(true), 8_000);
    return () => window.clearTimeout(timer);
  }, [degraded, error, loaded, connectionAttempt, config]);
  function handleVideoLoaded(event: SyntheticEvent<HTMLVideoElement>, isTalking: boolean) {
    setLoaded(value => value | (isTalking ? 2 : 1));
    const color = sampleMediaAmbientColor(event.currentTarget, event.currentTarget.videoWidth, event.currentTarget.videoHeight);
    if (!color || color === reportedAmbientColor.current) return;
    reportedAmbientColor.current = color;
    onAmbientColorChange?.(color);
  }

  function handleVideoError() {
    setError("动作视频加载失败，请检查素材后重试。");
  }

  useEffect(() => {
    if (loaded !== 3) return;
    const source = showingTalking ? idleRef.current : talkingRef.current;
    const target = showingTalking ? talkingRef.current : idleRef.current;
    if (!source || !target) return;
    if (Number.isFinite(target.duration) && target.duration > 0) target.currentTime = source.currentTime % target.duration;
    void target.play().catch(() => setError("动作播放被浏览器阻止，请重新进入会话。"));
  }, [showingTalking, loaded]);
  function retryMotion() {
    setDegraded(false);
    setConnectionAttempt((attempt) => attempt + 1);
  }

  function continueWithCurrentVisual() {
    setPair(null);
    setError("");
    setDegraded(true);
  }

  return <div className="digital-human-call-stage" data-render-path="orchestrated" data-renderer-state={degraded ? "degraded" : error ? "error" : loaded === 3 ? "ready" : "connecting"}>
    {pair && ([false, true] as const).map(isTalking => <video key={isTalking ? pair.talking : pair.idle} ref={isTalking ? talkingRef : idleRef} className="digital-human-live-video" src={isTalking ? pair.talking : pair.idle} autoPlay loop muted playsInline preload="auto" aria-label={isTalking ? "编排讲话画面" : "编排待机画面"} onLoadedData={(event) => handleVideoLoaded(event, isTalking)} onError={handleVideoError} style={{ opacity: isTalking === showingTalking ? 1 : 0, pointerEvents: "none" }} />)}
    {!degraded && !error && loaded !== 3 ? <div className="avatar-startup-dialog" role="status" aria-live="polite">
      <LoaderCircle aria-hidden="true" />
      <div>
        <strong>正在准备数字人</strong>
        <span>正在加载待机与讲话动作…</span>
        {showStartupFallback ? <button type="button" onClick={continueWithCurrentVisual}>使用当前画面继续</button> : null}
      </div>
    </div> : null}
    <div className="digital-human-call-copy">
      <span className="digital-human-state" role="status" aria-live="polite" aria-atomic="true">{statusLabel}</span>
      {caption && <p aria-live="polite">{caption}</p>}
      {error ? <div className="digital-human-recovery" role="alert">
        <span>{error}</span>
        <div className="digital-human-recovery-actions">
          <button type="button" onClick={retryMotion}>
            <RotateCcw aria-hidden="true" />重试素材
          </button>
          <button type="button" onClick={continueWithCurrentVisual}>使用当前画面继续</button>
        </div>
      </div> : degraded ? <div className="digital-human-recovery" role="status">
        <span>实时口型暂时不可用，已使用当前画面继续对话</span>
        <button type="button" onClick={retryMotion}><RotateCcw aria-hidden="true" />重试口型</button>
      </div> : null}
    </div>
  </div>;
}

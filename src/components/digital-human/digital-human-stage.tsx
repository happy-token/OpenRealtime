"use client";

import Image from "next/image";
import { MotionOrchestrationStage } from "./motion-orchestration";
import { LoaderCircle, RotateCcw } from "lucide-react";
import { useEffect, useRef, useState, type SyntheticEvent } from "react";
import type { ConversationState } from "@/hooks/use-voice-session";
import type { AvatarAudioSink } from "@/voice/audio/avatar-output";
import { getBuiltinMotionPreviewUrl } from "@/lib/builtin-motion-catalog";
import {
  fetchAvatarActionCatalog,
  selectAvatarActionRendition,
} from "@/lib/avatar-motion-catalog";
import { OPENTALKING_AVATAR_CATALOG } from "@/lib/opentalking-avatar-catalog";
import { prepareAvatarRendererAsset } from "@/lib/avatar-renderer-preparation-client";
import { readJsonResponse } from "@/lib/http-json-response";
import { getSegmentedAvatarRuntime } from "@/lib/segmented-avatar-runtime";
import { fetchOwnedAvatar } from "@/lib/avatar-catalog-client";
import { AnamAudioBridge } from "./anam-audio-bridge";
import { LiveTalkingAudioBridge } from "./livetalking-audio-bridge";
import { LiveTalkingSession } from "./livetalking-session";
import { AVATAR_IDENTITY_CHOICES, LIP_SYNC_CHOICES } from "./segmented-avatar-config";
import type { AvatarDisplayConfig } from "./types";
import { sampleMediaAmbientColor } from "@/lib/ambient-color";

interface DigitalHumanStageProps {
  state: ConversationState;
  statusLabel: string;
  currentTurnText: string;
  displayConfig: AvatarDisplayConfig;
  setAvatarAudioSink: (sink: AvatarAudioSink | null) => void;
  captionsEnabled?: boolean;
  onRendererReady?: () => void;
  onAmbientColorChange?: (color: string | null) => void;
}

type RendererState = "connecting" | "ready" | "preview" | "degraded" | "error";

interface TokenResponse {
  session_token?: string;
  avatar_model?: string;
  error?: string;
}

interface AvatarRendererRuntimeResponse {
  endpoint?: string;
  avatar_id?: string;
  model?: string;
  renderer?: string;
  error?: string;
}

export function DigitalHumanStage(props: DigitalHumanStageProps) {
  if (props.displayConfig.renderPath === "orchestrated") return <MotionOrchestrationStage config={props.displayConfig} speaking={props.state === "speaking"} onReady={props.onRendererReady} onAmbientColorChange={props.onAmbientColorChange} caption={props.captionsEnabled !== false ? props.currentTurnText : ""} statusLabel={props.statusLabel} />;
  return <RenderedDigitalHumanStage {...props} />;
}

function RenderedDigitalHumanStage({
  state,
  statusLabel,
  currentTurnText,
  displayConfig,
  setAvatarAudioSink,
  captionsEnabled = true,
  onRendererReady,
  onAmbientColorChange,
}: DigitalHumanStageProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const anamBridgeRef = useRef(new AnamAudioBridge(24_000));
  const liveTalkingBridgeRef = useRef(new LiveTalkingAudioBridge());
  const [rendererState, setRendererState] = useState<RendererState>("connecting");
  const [rendererMessage, setRendererMessage] = useState("正在启动数字人 Renderer");
  const [segmentedVideoUrl, setSegmentedVideoUrl] = useState("");
  const [segmentedTemporaryFit, setSegmentedTemporaryFit] = useState(false);
  const [connectionAttempt, setConnectionAttempt] = useState(0);
  const readyReported = useRef(false);
  const reportedAmbientColor = useRef<string | null>(null);

  useEffect(() => {
    readyReported.current = false;
  }, [displayConfig]);

  const segmentedRuntime = getSegmentedAvatarRuntime(displayConfig);
  const hasSegmentedRuntime = Boolean(segmentedRuntime);
  const conversationCanStart = rendererState === "ready";

  useEffect(() => {
    if (conversationCanStart && !readyReported.current) {
      readyReported.current = true;
      onRendererReady?.();
    }
  }, [conversationCanStart, onRendererReady]);

  useEffect(() => {
    const requestController = new AbortController();
    const bridge = anamBridgeRef.current;
    const liveTalkingBridge = liveTalkingBridgeRef.current;
    let cancelled = false;
    let session: import("@anam-ai/js-sdk").AnamClient | null = null;
    let liveTalkingSession: LiveTalkingSession | null = null;

    async function connect() {
      bridge.disconnect();
      liveTalkingBridge.disconnect();
      setAvatarAudioSink(null);
      setSegmentedVideoUrl("");
      setSegmentedTemporaryFit(false);
      if (displayConfig.renderPath === "segmented") {
        const lipModel = LIP_SYNC_CHOICES.find((choice) => choice.id === displayConfig.segmentedLipSyncId)?.name ?? "分段式 Renderer";
        if (hasSegmentedRuntime) {
          setRendererState("connecting");
          setRendererMessage(`正在检查 ${segmentedRuntime?.displayName ?? "数字人"} 的 Wav2Lip 资产`);
          try {
            const usesOwnedSource = usesOwnedAvatarSourceImage(displayConfig);
            const ownedAvatar = usesOwnedSource
              ? await fetchOwnedAvatar(displayConfig.segmentedAvatarId, requestController.signal)
              : null;
            const sourceImage = usesOwnedSource && ownedAvatar
              ? await fetch(ownedAvatar.source_image_url, { signal: requestController.signal }).then((response) => {
                if (!response.ok) throw new Error("Avatar 源图读取失败");
                return response.blob();
              })
              : undefined;
            const prepared = await prepareAvatarRendererAsset(displayConfig, {
              signal: requestController.signal,
              sourceImage,
              onProgress: (progress) => {
                setRendererMessage(`首次使用，正在准备 ${segmentedRuntime?.displayName ?? "数字人"} 的 Wav2Lip 资产 · ${progress}%`);
              },
            });
            if (cancelled) return;
            setRendererMessage("口型资产已准备 · 正在连接 Avatar Renderer");
            const response = await fetch("/api/avatar-renderer/session", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(displayConfig),
              cache: "no-store",
              signal: requestController.signal,
            });
            const payload = await readJsonResponse<AvatarRendererRuntimeResponse>(
              response,
              "Avatar Renderer 请求失败",
            );
            if (!response.ok || !payload.endpoint) {
              throw new Error(payload.error ?? "Avatar Renderer 不可用");
            }
            const video = videoRef.current;
            if (!video || cancelled) return;
            liveTalkingSession = new LiveTalkingSession(
              payload.endpoint,
              fetch,
              payload.avatar_id ?? prepared.rendererAssetId ?? segmentedRuntime?.avatarId,
            );
            const { sessionId } = await liveTalkingSession.connect(video);
            if (cancelled) return;
            liveTalkingBridge.connect(payload.endpoint, sessionId, video);
            setAvatarAudioSink(liveTalkingBridge);
            setRendererState("ready");
            setRendererMessage(`实时渲染已连接 · ${payload.model ?? "Wav2Lip 256"} · WebRTC`);
          } catch (error) {
            if (cancelled || requestController.signal.aborted) return;
            liveTalkingSession?.stop();
            liveTalkingBridge.disconnect();
            setRendererState("error");
            setRendererMessage(error instanceof Error ? error.message : "Wav2Lip 连接失败");
          }
          return;
        }
        const packagedIdentity = OPENTALKING_AVATAR_CATALOG.find(
          (asset) => asset.id === displayConfig.segmentedAvatarId,
        );
        if (!displayConfig.segmentedAvatarActionId && packagedIdentity) {
          setRendererState("preview");
          setRendererMessage(`${packagedIdentity.name}形象已加载 · ${lipModel} 仅口型对齐 · 无动作`);
          return;
        }
        if (displayConfig.segmentedAvatarActionId.startsWith("builtin:opentalking:")) {
          const assetId = displayConfig.segmentedAvatarActionId.slice("builtin:opentalking:".length);
          const packagedMotion = OPENTALKING_AVATAR_CATALOG.find(
            (asset) => asset.id === assetId && asset.motionVideoUrl,
          );
          if (!packagedMotion?.motionVideoUrl) {
            setRendererState("error");
            setRendererMessage("已选择的 OpenTalking 动作不可用，请回到配置重新选择");
            return;
          }
          setSegmentedVideoUrl(packagedMotion.motionVideoUrl);
          setRendererState("preview");
          setRendererMessage(`OpenTalking 配套动作已加载 · ${lipModel} 口型运行时待接入`);
          return;
        }
        if (displayConfig.segmentedAvatarActionId.startsWith("builtin:")) {
          const motionId = displayConfig.segmentedAvatarActionId.slice("builtin:".length);
          const previewUrl = getBuiltinMotionPreviewUrl(motionId);
          if (previewUrl) setSegmentedVideoUrl(previewUrl);
          setRendererState("preview");
          setRendererMessage(`内置动作底片配置已保存 · ${lipModel} 仅提供固定实验基线`);
          return;
        }
        setRendererState("connecting");
        setRendererMessage("正在读取已选择动作底片与当前画幅");
        try {
          const catalog = await fetchAvatarActionCatalog(displayConfig.segmentedAvatarId, fetch, requestController.signal);
          const selectedMotionBaseId = displayConfig.segmentedAvatarActionId || catalog.selection?.avatar_action_id;
          const motionBase = catalog.avatarActions.find((item) => item.avatar_action_id === selectedMotionBaseId);
          const playback = motionBase ? selectAvatarActionRendition(motionBase, displayConfig.ratio) : null;
          if (!selectedMotionBaseId) throw new Error(`${lipModel} 配置已保存 · 请选择已验收动作底片`);
          if (!motionBase || !playback?.rendition.artifact_id) throw new Error("已选择动作底片不可用，请回到配置重新选择");
          if (cancelled) return;
          setSegmentedVideoUrl(`/api/avatar-assets/artifacts/${encodeURIComponent(playback.rendition.artifact_id)}`);
          setSegmentedTemporaryFit(playback.temporaryFit);
          setRendererState("preview");
          setRendererMessage(`动作底片已加载${playback.temporaryFit ? " · 临时画幅适配" : ""} · ${lipModel} 口型运行时待接入`);
        } catch (error) {
          if (cancelled || requestController.signal.aborted) return;
          setRendererState("error");
          setRendererMessage(error instanceof Error ? error.message : "动作底片读取失败");
        }
        return;
      }
      if (displayConfig.provider !== "anam") {
        const pendingRenderer = displayConfig.provider === "heygen" ? "HeyGen LiveAvatar" : "自定义 Renderer";
        setRendererState("preview");
        setRendererMessage(`${pendingRenderer} 配置已保存 · 运行时 Adapter 待接入 · 当前使用普通音频`);
        return;
      }
      setRendererState("connecting");
      setRendererMessage("正在创建 Anam 实时会话");
      try {
        const response = await fetch("/api/anam/session", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(displayConfig.avatarProfileId === "default-anam"
            ? {}
            : { avatarId: displayConfig.avatarProfileId }),
          cache: "no-store",
          signal: requestController.signal,
        });
        const payload = await readJsonResponse<TokenResponse>(response, "Anam 会话请求失败");
        if (!response.ok || !payload.session_token) {
          throw new Error(payload.error ?? "Anam 会话创建失败");
        }
        const sdk = await import("@anam-ai/js-sdk");
        if (cancelled) return;
        session = sdk.createClient(payload.session_token, { disableInputAudio: true });
        session.addListener(sdk.AnamEvent.CONNECTION_CLOSED, () => {
          if (cancelled) return;
          setAvatarAudioSink(null);
          bridge.disconnect();
          setRendererState("degraded");
          setRendererMessage("数字人画面已中断 · 对话音频仍在继续");
        });
        session.addListener(sdk.AnamEvent.SERVER_WARNING, (message) => {
          if (!cancelled) setRendererMessage(`Anam 提示：${message}`);
        });
        await session.streamToVideoElement("anam-digital-human-video");
        const video = videoRef.current;
        if (!session || !video || cancelled) return;
        const audioInput = session.createAgentAudioInputStream({
          encoding: "pcm_s16le",
          sampleRate: 24_000,
          channels: 1,
        });
        bridge.connect(session, audioInput, video);
        setAvatarAudioSink(bridge);
        setRendererState("ready");
        setRendererMessage(`实时渲染已连接 · 百炼中文音色驱动 · ${payload.avatar_model ?? "cara-4"}`);
      } catch (error) {
        if (cancelled || requestController.signal.aborted) return;
        setAvatarAudioSink(null);
        bridge.disconnect();
        setRendererState("error");
        setRendererMessage(error instanceof Error ? error.message : "Anam 连接失败");
      }
    }

    void connect();
    return () => {
      cancelled = true;
      requestController.abort();
      setAvatarAudioSink(null);
      bridge.disconnect();
      liveTalkingBridge.disconnect();
      liveTalkingSession?.stop();
      if (session) void session.stopStreaming().catch(() => undefined);
      if (hasSegmentedRuntime) {
        void fetch("/api/avatar-renderer/session", { method: "DELETE", keepalive: true }).catch(() => undefined);
      }
    };
  }, [
    displayConfig,
    displayConfig.avatarProfileId,
    displayConfig.provider,
    displayConfig.ratio,
    displayConfig.renderPath,
    displayConfig.segmentedLipSyncId,
    displayConfig.segmentedAvatarActionId,
    displayConfig.segmentedAvatarId,
    connectionAttempt,
    setAvatarAudioSink,
    hasSegmentedRuntime,
    segmentedRuntime?.avatarId,
    segmentedRuntime?.displayName,
  ]);

  const selectedSegmentedAvatar = AVATAR_IDENTITY_CHOICES.find((choice) => choice.id === displayConfig.segmentedPresetId);
  const selectedOpenTalkingIdentity = OPENTALKING_AVATAR_CATALOG.find(
    (asset) => asset.id === displayConfig.segmentedAvatarId,
  );
  const hostedAvatarName = displayConfig.hostedAvatarDisplayName ?? "所选数字人";
  const fallbackImage = displayConfig.renderPath === "segmented"
    ? selectedOpenTalkingIdentity?.previewImageUrl ?? selectedSegmentedAvatar?.imageUrl
    : displayConfig.hostedAvatarImageUrl;
  const segmentedAvatarName = (displayConfig.segmentedDisplayName !== "Shuchang"
    || displayConfig.segmentedAvatarId === "shuchang"
    ? displayConfig.segmentedDisplayName
    : "") || selectedOpenTalkingIdentity?.name
    || selectedSegmentedAvatar?.name
    || "分段式";
  function reportAmbientColor(source: CanvasImageSource, sourceWidth: number, sourceHeight: number) {
    if (!onAmbientColorChange || sourceWidth < 1 || sourceHeight < 1) return;
    const color = sampleMediaAmbientColor(source, sourceWidth, sourceHeight);
    if (!color || color === reportedAmbientColor.current) return;
    reportedAmbientColor.current = color;
    onAmbientColorChange(color);
  }

  function handleFallbackImageLoad(event: SyntheticEvent<HTMLImageElement>) {
    reportAmbientColor(event.currentTarget, event.currentTarget.naturalWidth, event.currentTarget.naturalHeight);
  }

  function handleVideoMetadata(event: SyntheticEvent<HTMLVideoElement>) {
    reportAmbientColor(event.currentTarget, event.currentTarget.videoWidth, event.currentTarget.videoHeight);
  }

  return (
    <div
      className="digital-human-call-stage"
      data-state={state}
      data-renderer-state={rendererState}
      data-render-path={displayConfig.renderPath}
      data-surface={displayConfig.surface}
      data-framing={displayConfig.framing}
      data-ratio={displayConfig.ratio}
      data-quality={displayConfig.quality}
      data-hosted-avatar-id={displayConfig.renderPath === "hosted" ? displayConfig.avatarProfileId : undefined}
      data-motion-base-id={displayConfig.renderPath === "segmented" ? displayConfig.segmentedAvatarActionId || undefined : undefined}
      data-temporary-fit={displayConfig.renderPath === "segmented" ? segmentedTemporaryFit : undefined}
    >
      {fallbackImage ? <Image
        className="digital-human-call-backdrop"
        src={fallbackImage}
        alt=""
        aria-hidden="true"
        fill
        unoptimized={fallbackImage.startsWith("https://")}
        sizes="(max-width: 900px) 100vw, 900px"
      /> : null}
      {fallbackImage ? <Image
        className="digital-human-call-image"
        src={fallbackImage}
        alt={`${displayConfig.renderPath === "segmented" ? `${segmentedAvatarName} 数字人测试形象` : `${hostedAvatarName} 数字人形象`}`}
        fill
        priority
        unoptimized={fallbackImage.startsWith("https://")}
        sizes="(max-width: 900px) 100vw, 900px"
        onLoad={handleFallbackImageLoad}
      /> : <div className="digital-human-call-placeholder"><span>AVATAR ASSET</span><strong>{displayConfig.renderPath === "hosted" ? hostedAvatarName : selectedSegmentedAvatar?.name ?? "数字人形象"}</strong><small>预览资产将在 Renderer 接入后显示</small></div>}
      {displayConfig.renderPath === "hosted" && displayConfig.provider === "anam" && <video
        id="anam-digital-human-video"
        ref={videoRef}
        className="digital-human-live-video"
        autoPlay
        onLoadedData={handleVideoMetadata}
        playsInline
        aria-label="Anam 实时数字人画面"
      />}
      {segmentedRuntime && <video
        ref={videoRef}
        className="digital-human-live-video digital-human-wav2lip-video"
        autoPlay
        onLoadedData={handleVideoMetadata}
        playsInline
        aria-label="Wav2Lip 实时数字人画面"
      />}
      {displayConfig.renderPath === "segmented" && segmentedVideoUrl && <video
        className="digital-human-live-video digital-human-motion-base-video"
        src={segmentedVideoUrl}
        autoPlay
        onLoadedData={handleVideoMetadata}
        loop
        muted
        playsInline
        aria-label="已选择动作底片预览"
      />}
      <div className="digital-human-call-vignette" aria-hidden="true" />
      {rendererState === "connecting" && (
        <div className="avatar-startup-dialog" role="status" aria-live="polite">
          <LoaderCircle aria-hidden="true" />
          <div>
            <strong>正在按当前配置启动 Avatar</strong>
            <span>{rendererMessage || "正在初始化画面与口型服务，请稍候…"}</span>
          </div>
        </div>
      )}
      <div className="digital-human-call-copy">
        <span className="digital-human-state"><i />{statusLabel}</span>
        {captionsEnabled && currentTurnText.trim() ? (
          <p aria-live="polite">{currentTurnText}</p>
        ) : null}
        {(rendererState === "degraded" || rendererState === "error") && (
          <div className="digital-human-recovery" role="status">
            <span>{rendererMessage}</span>
            <button type="button" aria-label="重新连接数字人画面" onClick={() => setConnectionAttempt((attempt) => attempt + 1)}>
              <RotateCcw aria-hidden="true" />
              重连画面
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export function usesOwnedAvatarSourceImage(displayConfig: AvatarDisplayConfig) {
  return displayConfig.segmentedAvatarActionId === `builtin:identity-static:${displayConfig.segmentedAvatarId}`;
}

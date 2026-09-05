"use client";

import Image from "next/image";
import Link from "next/link";
import { ArrowLeft, Check, ChevronDown, CircleAlert, Eye, LoaderCircle, RefreshCw, Upload, Wand2, X } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState, type CSSProperties, type KeyboardEvent } from "react";
import { DEFAULT_AVATAR_DISPLAY_CONFIG } from "@/components/digital-human/types";
import { StudioConfigOverlay } from "./studio-config-overlay";
import {
  appendOwnedAvatarAction,
  fetchOwnedAvatar,
} from "@/lib/avatar-catalog-client";
import type { OwnedAvatarRecord } from "@/lib/avatar-records";
import { prepareAvatarRendererAsset } from "@/lib/avatar-renderer-preparation-client";
import { LIVEPORTRAIT_ACTIONS, type LivePortraitActionId } from "@/lib/liveportrait-actions";
import {
  createLivePortraitMotionConfig,
  LIVEPORTRAIT_STRENGTH_MULTIPLIERS,
} from "@/lib/liveportrait-motion-config";
import { readJsonResponse } from "@/lib/http-json-response";
import { classifyMediaAspectRatio, type MediaAspectBucket } from "@/lib/media-aspect-fit";
import {
  VIDEO_GENERATION_DEFAULT_MODELS,
  VIDEO_GENERATION_MODELS,
  VIDEO_GENERATION_PROVIDERS,
  composeVideoGenerationPrompt,
  LTX_PROMPT_PRESETS,
  VIDEO_PROMPT_STYLES,
  type VideoGenerationModelId,
  type VideoGenerationProvider,
  type VideoPromptStyleId,
} from "@/lib/ltx-avatar-action";
import {
  MINIMAX_DURATIONS,
  MINIMAX_RATIOS,
  type MiniMaxDuration,
  type MiniMaxImageRole,
  type MiniMaxRatio,
  type MiniMaxResolution,
} from "@/lib/minimax-video-options";
import styles from "./avatar-action-studio.module.css";

type TaskState = "idle" | "queueing" | "processing" | "success" | "failed";
type RuntimeState = "checking" | "ready" | "error";
type ActionProvider = "liveportrait" | "ltx";
type TaskProvider = ActionProvider | "minimax";
type MotionSourceMode = "template" | "upload";
type PreviewMode = "avatar" | "reference" | "result";
type Rendition = {
  rendition_id: string;
  phase: "queued" | "processing" | "ready_for_review" | "approved" | "failed";
  artifact_id?: string;
  media?: { duration_ms: number };
};
type MotionBase = {
  avatar_action_id: string;
  phase: "preparing" | "ready";
  renditions: Rendition[];
  error?: string;
};

const MOTION_MULTIPLIER_MIN = 0.5;
const MOTION_MULTIPLIER_MAX = 1.5;
const MOTION_STRENGTH_PRESETS = [
  { value: LIVEPORTRAIT_STRENGTH_MULTIPLIERS.subtle, label: "轻微", detail: "克制微动" },
  { value: LIVEPORTRAIT_STRENGTH_MULTIPLIERS.natural, label: "自然", detail: "默认推荐" },
  { value: LIVEPORTRAIT_STRENGTH_MULTIPLIERS.expressive, label: "明显", detail: "表现突出" },
] as const;
type VideoPromptChoiceId = VideoPromptStyleId | "custom";
const VIDEO_PROMPT_CHOICES: ReadonlyArray<{ id: VideoPromptChoiceId; name: string; description: string }> = [
  ...VIDEO_PROMPT_STYLES,
  { id: "custom", name: "自定义提示词", description: "直接编辑完整动作描述" },
];
const MINIMAX_IMAGE_ROLE_OPTIONS: ReadonlyArray<{ value: MiniMaxImageRole; label: string; detail: string }> = [
  { value: "first_and_last_frame", label: "首帧 + 尾帧", detail: "同一数字人形象同时作为 first_frame 与 last_frame" },
  { value: "first_frame", label: "仅首帧", detail: "视频从数字人形象开始 · first_frame" },
  { value: "last_frame", label: "仅尾帧", detail: "视频最终回到数字人形象 · last_frame" },
  { value: "reference_image", label: "多模态参考图", detail: "作为 reference_image，可与参考视频组合" },
];

const GENERATION_ESTIMATED_DURATION_MS: Record<TaskProvider, number> = {
  liveportrait: 40_000,
  ltx: 70_000,
  minimax: 150_000,
};
const GENERATION_PROGRESS_CAP = 0.96;
const ELAPSED_TICK_MS = 500;

export function estimateGenerationProgress(elapsedMs: number, taskSource: TaskProvider): number {
  return Math.min(GENERATION_PROGRESS_CAP, 1 - Math.exp(-elapsedMs / GENERATION_ESTIMATED_DURATION_MS[taskSource]));
}

export function formatElapsedTime(elapsedMs: number): string {
  const totalSeconds = Math.max(0, Math.floor(elapsedMs / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function GenerationParameterSelect({
  label,
  ariaLabel,
  value,
  options,
  disabled = false,
  onChange,
}: {
  label: string;
  ariaLabel: string;
  value: string;
  options: ReadonlyArray<{ value: string; label: string; detail?: string }>;
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [focusedValue, setFocusedValue] = useState(value);
  const root = useRef<HTMLDivElement>(null);
  const listboxId = useId();
  const selected = options.find((option) => option.value === value) ?? options[0];

  useEffect(() => {
    if (!open) return;
    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    return () => document.removeEventListener("pointerdown", closeOnOutsidePointer);
  }, [open]);

  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  function select(nextValue: string) {
    if (disabled) return;
    setFocusedValue(nextValue);
    setOpen(false);
    onChange(nextValue);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key === "Escape") return setOpen(false);
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const currentIndex = options.findIndex((option) => option.value === focusedValue);
      const direction = event.key === "ArrowDown" ? 1 : -1;
      setFocusedValue(options[(currentIndex + direction + options.length) % options.length].value);
      setOpen(true);
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (open) select(focusedValue);
      else {
        setFocusedValue(value);
        setOpen(true);
      }
    }
  }

  return <div className={styles.miniMaxParameterField}>
    <span>{label}</span>
    <div
      className={`${styles.actionSelect} ${styles.parameterSelect}`}
      ref={root}
      data-open={open}
      data-detailed={options.some((option) => option.detail) || undefined}
    >
      <button
        className={styles.actionSelectTrigger}
        type="button"
        role="combobox"
        aria-label={ariaLabel}
        aria-controls={listboxId}
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-activedescendant={open ? `${listboxId}-${focusedValue.replace(/[^A-Za-z0-9_-]/g, "-")}` : undefined}
        disabled={disabled}
        onClick={() => {
          setFocusedValue(value);
          setOpen((current) => !current);
        }}
        onKeyDown={handleKeyDown}
      >
        <span className={styles.actionSelectValue}><strong>{selected.label}</strong></span>
        <ChevronDown aria-hidden="true" />
      </button>
      <div className={styles.actionSelectMenu} id={listboxId} role="listbox" aria-label={`${ariaLabel}选项`} hidden={!open}>
        {options.map((option) => {
          const optionId = `${listboxId}-${option.value.replace(/[^A-Za-z0-9_-]/g, "-")}`;
          return <button
            id={optionId}
            key={option.value}
            type="button"
            role="option"
            aria-selected={option.value === value}
            data-focused={option.value === focusedValue}
            onPointerEnter={() => setFocusedValue(option.value)}
            onClick={() => select(option.value)}
          >
            <span className={styles.actionOptionCopy}><strong>{option.label}</strong>{option.detail ? <small>{option.detail}</small> : null}</span>
            <Check aria-hidden="true" />
          </button>;
        })}
      </div>
    </div>
  </div>;
}

export function AvatarActionStudio({
  avatarId,
  embedded = false,
  initialProvider = "liveportrait",
  previewImageUrl = "",
  onChangeAvatar,
  onPreviewAvatar,
  mobileConfigOpen,
  onMobileConfigOpenChange,
}: {
  avatarId: string;
  embedded?: boolean;
  initialProvider?: ActionProvider;
  previewImageUrl?: string;
  onChangeAvatar?: () => void;
  onPreviewAvatar?: () => void;
  mobileConfigOpen?: boolean;
  onMobileConfigOpenChange?: (open: boolean) => void;
}) {
  const [avatar, setAvatar] = useState<OwnedAvatarRecord | null>(null);
  const [provider, setProvider] = useState<ActionProvider>(initialProvider);
  const [livePortraitRuntime, setLivePortraitRuntime] = useState<RuntimeState>("checking");
  const [livePortraitRuntimeMessage, setLivePortraitRuntimeMessage] = useState("");
  const [ltxRuntime, setLtxRuntime] = useState<RuntimeState>("checking");
  const [ltxRuntimeMessage, setLtxRuntimeMessage] = useState("");
  const [availableTemplates, setAvailableTemplates] = useState<Set<string>>(new Set());
  const [motionSourceMode, setMotionSourceMode] = useState<MotionSourceMode>("template");
  const [selectedActionId, setSelectedActionId] = useState<LivePortraitActionId>(LIVEPORTRAIT_ACTIONS[0].id);
  const [focusedActionId, setFocusedActionId] = useState<LivePortraitActionId>(LIVEPORTRAIT_ACTIONS[0].id);
  const [actionMenuOpen, setActionMenuOpen] = useState(false);
  const [drivingFile, setDrivingFile] = useState<File | null>(null);
  const [drivingPreviewUrl, setDrivingPreviewUrl] = useState("");
  const [previewMode, setPreviewMode] = useState<PreviewMode>("avatar");
  const [previewFit, setPreviewFit] = useState<MediaAspectBucket>("square");
  const [motionMultiplier, setMotionMultiplier] = useState(1);
  const [actionName, setActionName] = useState(initialProvider === "ltx" ? VIDEO_PROMPT_STYLES[0].name : LIVEPORTRAIT_ACTIONS[0].name);
  const [livePortraitActionName, setLivePortraitActionName] = useState(LIVEPORTRAIT_ACTIONS[0].name);
  const [ltxActionName, setLtxActionName] = useState<string>(VIDEO_PROMPT_STYLES[0].name);
  const [ltxModel, setLtxModel] = useState<VideoGenerationModelId>(VIDEO_GENERATION_DEFAULT_MODELS.minimax);
  const [videoVendor, setVideoVendor] = useState<VideoGenerationProvider>("minimax");
  const [focusedVideoVendor, setFocusedVideoVendor] = useState<VideoGenerationProvider>("minimax");
  const [videoVendorMenuOpen, setVideoVendorMenuOpen] = useState(false);
  const [focusedVideoModel, setFocusedVideoModel] = useState<VideoGenerationModelId>(VIDEO_GENERATION_DEFAULT_MODELS.minimax);
  const [videoModelMenuOpen, setVideoModelMenuOpen] = useState(false);
  const [videoPromptChoiceId, setVideoPromptChoiceId] = useState<VideoPromptChoiceId>(VIDEO_PROMPT_STYLES[0].id);
  const [focusedVideoPromptChoiceId, setFocusedVideoPromptChoiceId] = useState<VideoPromptChoiceId>(VIDEO_PROMPT_STYLES[0].id);
  const [ltxPromptMenuOpen, setLtxPromptMenuOpen] = useState(false);
  const [ltxPrompt, setLtxPrompt] = useState<string>(() => composeVideoGenerationPrompt(LTX_PROMPT_PRESETS[0].id, "sweet-vitality"));
  const [customLtxPrompt, setCustomLtxPrompt] = useState("");
  const [miniMaxRatio, setMiniMaxRatio] = useState<MiniMaxRatio>("16:9");
  const [miniMaxResolution, setMiniMaxResolution] = useState<MiniMaxResolution>("768P");
  const [miniMaxDuration, setMiniMaxDuration] = useState<MiniMaxDuration>(6);
  const [miniMaxImageRole, setMiniMaxImageRole] = useState<MiniMaxImageRole>("first_and_last_frame");
  const [miniMaxReferenceVideo, setMiniMaxReferenceVideo] = useState<File | null>(null);
  const [miniMaxReferencePreviewUrl, setMiniMaxReferencePreviewUrl] = useState("");
  const [promptModalOpen, setPromptModalOpen] = useState(false);
  const [taskState, setTaskState] = useState<TaskState>("idle");
  const [taskId, setTaskId] = useState("");
  const [taskProvider, setTaskProvider] = useState<TaskProvider>("liveportrait");
  const [resultUrl, setResultUrl] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [savedActionId, setSavedActionId] = useState("");
  const [elapsedMs, setElapsedMs] = useState(0);
  const submissionLock = useRef(false);
  const generationStartedAtRef = useRef(0);
  const drivingInput = useRef<HTMLInputElement>(null);
  const miniMaxReferenceInput = useRef<HTMLInputElement>(null);
  const actionSelect = useRef<HTMLDivElement>(null);
  const ltxPromptSelect = useRef<HTMLDivElement>(null);
  const videoModelSelect = useRef<HTMLDivElement>(null);
  const videoVendorSelect = useRef<HTMLDivElement>(null);
  const promptDialog = useRef<HTMLDialogElement>(null);
  const promptViewButton = useRef<HTMLButtonElement>(null);
  const actionListboxId = useId();
  const ltxPromptListboxId = useId();
  const videoModelListboxId = useId();
  const videoVendorListboxId = useId();
  const uploadMotionHintId = useId();
  const miniMaxUploadHintId = useId();

  const checkLivePortraitRuntime = useCallback(async () => {
    setLivePortraitRuntime("checking");
    try {
      const response = await fetch("/api/liveportrait", { cache: "no-store" });
      const payload = await response.json() as { ready?: boolean; error?: string; issues?: string[]; templates?: Array<{ id: string; available: boolean }> };
      if (!response.ok || !payload.ready) throw new Error(payload.error || payload.issues?.[0] || "LivePortrait 暂不可用");
      setAvailableTemplates(new Set(payload.templates?.filter((item) => item.available).map((item) => item.id) ?? []));
      setLivePortraitRuntime("ready");
      setLivePortraitRuntimeMessage("");
    } catch (runtimeError) {
      setLivePortraitRuntime("error");
      setLivePortraitRuntimeMessage(runtimeError instanceof Error ? runtimeError.message : "LivePortrait 暂不可用");
    }
  }, []);

  const checkLtxRuntime = useCallback(async () => {
    setLtxRuntime("checking");
    try {
      const response = await fetch("/api/ltx/image-to-video", { cache: "no-store" });
      const payload = await response.json() as { ready?: boolean; error?: string };
      if (!response.ok || !payload.ready) throw new Error(payload.error || "视频生成暂不可用");
      setLtxRuntime("ready");
      setLtxRuntimeMessage("");
    } catch (runtimeError) {
      setLtxRuntime("error");
      setLtxRuntimeMessage(runtimeError instanceof Error ? runtimeError.message : "视频生成暂不可用");
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void fetchOwnedAvatar(avatarId, controller.signal).then(setAvatar).catch(() => undefined);
    void checkLivePortraitRuntime();
    void checkLtxRuntime();
    return () => controller.abort();
  }, [avatarId, checkLivePortraitRuntime, checkLtxRuntime]);

  useEffect(() => {
    if (!drivingFile) {
      setDrivingPreviewUrl("");
      return;
    }
    const objectUrl = URL.createObjectURL(drivingFile);
    setDrivingPreviewUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [drivingFile]);

  useEffect(() => {
    if (!miniMaxReferenceVideo) {
      setMiniMaxReferencePreviewUrl("");
      return;
    }
    const objectUrl = URL.createObjectURL(miniMaxReferenceVideo);
    setMiniMaxReferencePreviewUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [miniMaxReferenceVideo]);

  useEffect(() => {
    if (!actionMenuOpen && !ltxPromptMenuOpen && !videoModelMenuOpen && !videoVendorMenuOpen) return;
    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (!actionSelect.current?.contains(event.target as Node)) setActionMenuOpen(false);
      if (!ltxPromptSelect.current?.contains(event.target as Node)) setLtxPromptMenuOpen(false);
      if (!videoModelSelect.current?.contains(event.target as Node)) setVideoModelMenuOpen(false);
      if (!videoVendorSelect.current?.contains(event.target as Node)) setVideoVendorMenuOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    return () => document.removeEventListener("pointerdown", closeOnOutsidePointer);
  }, [actionMenuOpen, ltxPromptMenuOpen, videoModelMenuOpen, videoVendorMenuOpen]);

  useEffect(() => {
    if (!promptModalOpen) return;
    const dialog = promptDialog.current;
    if (dialog && !dialog.open) dialog.showModal();
  }, [promptModalOpen]);

  const pollTask = useCallback(async (id: string, taskSource: TaskProvider, signal?: AbortSignal) => {
    try {
      const endpoint = taskSource === "liveportrait"
        ? `/api/liveportrait/${encodeURIComponent(id)}`
        : `/api/ltx/image-to-video/${encodeURIComponent(id)}`;
      const response = await fetch(endpoint, { cache: "no-store", signal });
      const payload = await response.json() as { state?: TaskState; result_url?: string; error?: string };
      if (!response.ok) throw new Error(payload.error || "动作状态读取失败");
      const next = payload.state ?? "failed";
      setTaskState(next);
      if (next === "success" && payload.result_url) {
        setResultUrl(payload.result_url);
        setPreviewMode("result");
      }
      if (next === "failed") setError(payload.error || "动作生成失败");
      return next;
    } catch (pollError) {
      if (pollError instanceof Error && pollError.name === "AbortError") return undefined;
      setError(pollError instanceof Error ? pollError.message : "动作状态读取失败");
      setTaskState("failed");
      return "failed" as const;
    }
  }, []);

  useEffect(() => {
    if (!taskId || (taskState !== "queueing" && taskState !== "processing")) return;
    let cancelled = false;
    let controller: AbortController | null = null;
    let timer = window.setTimeout(async function poll() {
      controller = new AbortController();
      const next = await pollTask(taskId, taskProvider, controller.signal);
      if (!cancelled && next !== "success" && next !== "failed") timer = window.setTimeout(poll, taskProvider === "liveportrait" ? 2_000 : 5_000);
    }, 500);
    return () => {
      cancelled = true;
      controller?.abort();
      window.clearTimeout(timer);
    };
  }, [pollTask, taskId, taskProvider, taskState]);

  const busy = taskState === "queueing" || taskState === "processing";

  useEffect(() => {
    if (!busy) return;
    const updateElapsed = () => setElapsedMs(Date.now() - generationStartedAtRef.current);
    updateElapsed();
    const interval = window.setInterval(updateElapsed, ELAPSED_TICK_MS);
    return () => window.clearInterval(interval);
  }, [busy]);

  useEffect(() => {
    if (!busy) return;
    const confirmBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", confirmBeforeUnload);
    return () => window.removeEventListener("beforeunload", confirmBeforeUnload);
  }, [busy]);

  async function generatePreview() {
    const activeRuntime = provider === "ltx" ? ltxRuntime : livePortraitRuntime;
    if (
      !avatar
      || activeRuntime !== "ready"
      || submissionLock.current
      || (provider === "ltx" && !ltxPrompt.trim())
      || (provider === "liveportrait" && motionSourceMode === "upload" && !drivingFile)
    ) return;
    submissionLock.current = true;
    generationStartedAtRef.current = Date.now();
    setElapsedMs(0);
    setTaskState("queueing");
    setTaskProvider(provider === "liveportrait" ? "liveportrait" : videoVendor);
    setError("");
    setSavedActionId("");
    try {
      let response: Response;
      if (provider === "ltx") {
        if (videoVendor === "minimax") {
          const form = new FormData();
          form.set("avatarId", avatar.avatar_id);
          form.set("prompt", ltxPrompt);
          form.set("model", ltxModel);
          form.set("ratio", miniMaxRatio);
          form.set("resolution", miniMaxResolution);
          form.set("duration", String(miniMaxDuration));
          form.set("imageRole", miniMaxImageRole);
          form.set("creditsAccepted", "true");
          form.set("rightsConfirmed", "true");
          if (miniMaxReferenceVideo) form.set("referenceVideo", miniMaxReferenceVideo);
          response = await fetch("/api/ltx/image-to-video", { method: "POST", body: form });
        } else {
          response = await fetch("/api/ltx/image-to-video", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              avatarId: avatar.avatar_id,
              prompt: ltxPrompt,
              model: ltxModel,
              creditsAccepted: true,
              rightsConfirmed: true,
            }),
          });
        }
      } else {
        const sourceResponse = await fetch(avatar.source_image_url);
        if (!sourceResponse.ok) throw new Error("Avatar 源图读取失败");
        const sourceBlob = await sourceResponse.blob();
        const form = new FormData();
        form.set("source", new File([sourceBlob], `${avatar.display_name}.jpg`, { type: sourceBlob.type || "image/jpeg" }));
        form.set("avatarId", avatar.avatar_id);
        form.set("driverId", motionSourceMode === "upload" ? "upload" : selectedActionId);
        form.set("livePortraitConfig", JSON.stringify(createLivePortraitMotionConfig({ drivingMultiplier: motionMultiplier })));
        if (motionSourceMode === "upload" && drivingFile) form.set("driving", drivingFile);
        form.set("rightsConfirmed", "true");
        response = await fetch("/api/liveportrait", { method: "POST", body: form });
      }
      const payload = await response.json() as { task_id?: string; state?: TaskState; error?: string };
      if (!response.ok || !payload.task_id) throw new Error(payload.error || "动作任务创建失败");
      setTaskId(payload.task_id);
      setTaskState(payload.state ?? "queueing");
      onMobileConfigOpenChange?.(false);
    } catch (generationError) {
      setTaskState("failed");
      setError(generationError instanceof Error ? generationError.message : "动作生成失败");
    } finally {
      submissionLock.current = false;
    }
  }

  function selectProvider(nextProvider: ActionProvider) {
    if (busy || nextProvider === provider) return;
    setProvider(nextProvider);
    setActionMenuOpen(false);
    setLtxPromptMenuOpen(false);
    setVideoModelMenuOpen(false);
    setVideoVendorMenuOpen(false);
    setActionName(nextProvider === "ltx" ? ltxActionName : livePortraitActionName);
    setPreviewMode("avatar");
    setResultUrl("");
    setTaskId("");
    setTaskState("idle");
    setSavedActionId("");
    setError("");
  }

  function selectVideoPromptChoice(value: VideoPromptChoiceId) {
    if (busy) return;
    setVideoPromptChoiceId(value);
    setFocusedVideoPromptChoiceId(value);
    setLtxPromptMenuOpen(false);
    if (value === "custom") {
      setLtxPrompt(customLtxPrompt);
      setActionName("自定义动作");
      setLtxActionName("自定义动作");
    } else {
      const style = VIDEO_PROMPT_STYLES.find((item) => item.id === value);
      if (!style) return;
      setLtxPrompt(composeVideoGenerationPrompt("video-conversation", style.id));
      setActionName(style.name);
      setLtxActionName(style.name);
    }
    setResultUrl("");
    setTaskId("");
    setTaskState("idle");
    setSavedActionId("");
  }

  function closePromptModal() {
    const dialog = promptDialog.current;
    if (dialog?.open) dialog.close();
    else setPromptModalOpen(false);
  }

  function selectDrivingFile(file?: File) {
    if (!file) return;
    setError("");
    if (!["video/mp4", "video/webm", "video/quicktime"].includes(file.type)) {
      setError("动作参考仅支持 MP4、WebM 或 MOV");
      return;
    }
    if (!file.size) {
      setError("动作参考不能为空");
      return;
    }
    if (file.size > 50 * 1024 * 1024) {
      setError("动作参考不能超过 50MB");
      return;
    }
    setDrivingFile(file);
    setMotionSourceMode("upload");
    const nextName = file.name.replace(/\.[^.]+$/, "").slice(0, 50) || "自定义参考动作";
    setActionName(nextName);
    setLivePortraitActionName(nextName);
    setPreviewMode("reference");
    setResultUrl("");
    setSavedActionId("");
  }

  function selectTemplateAction(actionId: string) {
    if (busy) return;
    const action = LIVEPORTRAIT_ACTIONS.find((candidate) => candidate.id === actionId);
    if (!action) return;
    setSelectedActionId(action.id);
    setFocusedActionId(action.id);
    setActionMenuOpen(false);
    setDrivingFile(null);
    setMotionSourceMode("template");
    setActionName(action.name);
    setLivePortraitActionName(action.name);
    setMotionMultiplier(LIVEPORTRAIT_STRENGTH_MULTIPLIERS[action.recommendedStrength]);
    setPreviewMode("reference");
    setResultUrl("");
    setTaskId("");
    setTaskState("idle");
    setSavedActionId("");
  }

  function handleActionPickerKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key === "Escape") {
      setActionMenuOpen(false);
      return;
    }
    const selectableActions = LIVEPORTRAIT_ACTIONS.filter((action) => livePortraitRuntime !== "ready" || availableTemplates.has(action.id));
    if (!selectableActions.length) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const currentIndex = selectableActions.findIndex((action) => action.id === focusedActionId);
      const direction = event.key === "ArrowDown" ? 1 : -1;
      const nextIndex = currentIndex < 0
        ? 0
        : (currentIndex + direction + selectableActions.length) % selectableActions.length;
      setFocusedActionId(selectableActions[nextIndex].id);
      setActionMenuOpen(true);
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (actionMenuOpen) selectTemplateAction(focusedActionId);
      else {
        setFocusedActionId(selectedActionId);
        setActionMenuOpen(true);
      }
    }
  }

  function handleLtxPromptPickerKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key === "Escape") {
      setLtxPromptMenuOpen(false);
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const currentIndex = VIDEO_PROMPT_CHOICES.findIndex((choice) => choice.id === focusedVideoPromptChoiceId);
      const direction = event.key === "ArrowDown" ? 1 : -1;
      const nextIndex = currentIndex < 0
        ? 0
        : (currentIndex + direction + VIDEO_PROMPT_CHOICES.length) % VIDEO_PROMPT_CHOICES.length;
      setFocusedVideoPromptChoiceId(VIDEO_PROMPT_CHOICES[nextIndex].id);
      setLtxPromptMenuOpen(true);
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (ltxPromptMenuOpen) selectVideoPromptChoice(focusedVideoPromptChoiceId);
      else {
        setFocusedVideoPromptChoiceId(videoPromptChoiceId);
        setLtxPromptMenuOpen(true);
      }
    }
  }

  function resetGeneratedPreview() {
    setResultUrl("");
    setTaskId("");
    setTaskState("idle");
    setSavedActionId("");
  }

  function selectVideoVendor(value: VideoGenerationProvider) {
    if (busy) return;
    const defaultModel = VIDEO_GENERATION_DEFAULT_MODELS[value];
    setVideoVendor(value);
    setFocusedVideoVendor(value);
    setVideoVendorMenuOpen(false);
    setLtxModel(defaultModel);
    setFocusedVideoModel(defaultModel);
    if (value === "ltx") setPreviewMode("avatar");
    resetGeneratedPreview();
  }

  function handleVideoVendorPickerKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key === "Escape") return setVideoVendorMenuOpen(false);
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const index = VIDEO_GENERATION_PROVIDERS.findIndex((item) => item.id === focusedVideoVendor);
      const direction = event.key === "ArrowDown" ? 1 : -1;
      setFocusedVideoVendor(VIDEO_GENERATION_PROVIDERS[(index + direction + VIDEO_GENERATION_PROVIDERS.length) % VIDEO_GENERATION_PROVIDERS.length].id);
      setVideoVendorMenuOpen(true);
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (videoVendorMenuOpen) selectVideoVendor(focusedVideoVendor);
      else {
        setFocusedVideoVendor(videoVendor);
        setVideoVendorMenuOpen(true);
      }
    }
  }

  function selectVideoModel(value: VideoGenerationModelId) {
    if (busy) return;
    setLtxModel(value);
    setFocusedVideoModel(value);
    setVideoModelMenuOpen(false);
    if (value === "MiniMax-H3-Max") {
      setMiniMaxImageRole("first_and_last_frame");
      setMiniMaxReferenceVideo(null);
      if (miniMaxResolution === "2K") setMiniMaxResolution("768P");
      if (miniMaxDuration === 4) setMiniMaxDuration(5);
    }
    resetGeneratedPreview();
  }

  function handleVideoModelPickerKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key === "Escape") {
      setVideoModelMenuOpen(false);
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const models = VIDEO_GENERATION_MODELS.filter((model) => model.provider === videoVendor);
      const currentIndex = models.findIndex((model) => model.id === focusedVideoModel);
      const direction = event.key === "ArrowDown" ? 1 : -1;
      const nextIndex = currentIndex < 0
        ? 0
        : (currentIndex + direction + models.length) % models.length;
      setFocusedVideoModel(models[nextIndex].id);
      setVideoModelMenuOpen(true);
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (videoModelMenuOpen) selectVideoModel(focusedVideoModel);
      else {
        setFocusedVideoModel(ltxModel);
        setVideoModelMenuOpen(true);
      }
    }
  }

  function selectMiniMaxReferenceVideo(file?: File) {
    if (!file) return;
    setError("");
    if (ltxModel === "MiniMax-H3-Max") return setError("H3 Max 不支持参考视频，请改用 H3");
    const inferredType = file.type || (file.name.toLowerCase().endsWith(".mov") ? "video/quicktime" : file.name.toLowerCase().endsWith(".mp4") ? "video/mp4" : "");
    if (inferredType !== "video/mp4" && inferredType !== "video/quicktime") return setError("MiniMax 参考视频仅支持 MP4 或 MOV");
    if (!file.size) return setError("参考视频不能为空");
    if (file.size > 50 * 1024 * 1024) return setError("参考视频不能超过 50MB");
    setMiniMaxReferenceVideo(file.type ? file : new File([file], file.name, { type: inferredType, lastModified: file.lastModified }));
    setMiniMaxImageRole("reference_image");
    setPreviewMode("reference");
    resetGeneratedPreview();
  }

  function updateMotionMultiplier(value: number) {
    const nextValue = Math.min(MOTION_MULTIPLIER_MAX, Math.max(MOTION_MULTIPLIER_MIN, Number(value.toFixed(2))));
    setMotionMultiplier(nextValue);
    setResultUrl("");
    setTaskId("");
    setTaskState("idle");
    setSavedActionId("");
  }

  async function createActionAsset() {
    if (!avatar || !taskId || !resultUrl || saving) return;
    setSaving(true);
    setError("");
    try {
      const candidateResponse = await fetch("/api/avatar-assets/candidates/provider", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sourceKind: taskProvider,
          taskId,
          avatarId: avatar.avatar_id,
          idempotencyKey: crypto.randomUUID(),
          rightsConfirmed: true,
        }),
      });
      const candidate = await readJsonResponse<{ candidate_id?: string; error?: string }>(
        candidateResponse,
        "动作候选保存失败",
      );
      if (!candidateResponse.ok || !candidate.candidate_id) throw new Error(candidate.error || "动作候选保存失败");
      const acceptResponse = await fetch(`/api/avatar-assets/candidates/${encodeURIComponent(candidate.candidate_id)}/accept`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          idempotencyKey: crypto.randomUUID(),
          checks: {
            identity_match: true,
            single_person: true,
            closed_mouth: true,
            fixed_camera: true,
            no_gestures: true,
            rights_confirmed: true,
          },
        }),
      });
      let motion = await readJsonResponse<MotionBase>(acceptResponse, "动作适配失败");
      if (!acceptResponse.ok || !motion.avatar_action_id) throw new Error(motion.error || "动作适配失败");
      for (const rendition of motion.renditions.filter((item) => item.phase === "ready_for_review" && item.media)) {
        const response = await fetch(`/api/avatar-assets/renditions/${encodeURIComponent(rendition.rendition_id)}/approve`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            startMs: 0,
            endMs: rendition.media!.duration_ms,
            crossfadeMs: Math.min(100, Math.floor(rendition.media!.duration_ms / 4)),
          }),
        });
        const approved = await readJsonResponse<MotionBase>(response, "动作画幅适配失败");
        if (!response.ok) throw new Error(approved.error || "动作画幅适配失败");
        motion = approved;
      }
      if (motion.phase !== "ready") throw new Error("动作仍在适配，请稍后再次创建");
      const playback = motion.renditions.find((item) => item.phase === "approved" && item.artifact_id);
      const videoUrl = playback?.artifact_id ? `/api/avatar-assets/artifacts/${encodeURIComponent(playback.artifact_id)}` : resultUrl;
      await appendOwnedAvatarAction(avatar.avatar_id, {
        avatar_action_id: motion.avatar_action_id,
        display_name: actionName,
        video_url: videoUrl,
        pending_model_count: 1,
      });
      setSavedActionId(motion.avatar_action_id);
      onMobileConfigOpenChange?.(false);
      void prepareAllEnabledModels(avatar, motion.avatar_action_id);
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "动作资产创建失败");
    } finally {
      setSaving(false);
    }
  }

  async function prepareAllEnabledModels(currentAvatar: OwnedAvatarRecord, avatarActionId: string) {
    try {
      await prepareAvatarRendererAsset({
        ...DEFAULT_AVATAR_DISPLAY_CONFIG,
        renderPath: "segmented",
        segmentedPresetId: currentAvatar.avatar_id,
        segmentedAvatarId: currentAvatar.avatar_id,
        segmentedAvatarActionId: avatarActionId,
        segmentedLipSyncId: "wav2lip256",
      });
    } catch (preparationError) {
      setError(preparationError instanceof Error
        ? `动作已保存，但口型预处理失败：${preparationError.message}`
        : "动作已保存，但口型预处理失败");
    }
  }

  const generationProgress = busy ? estimateGenerationProgress(elapsedMs, taskProvider) : 0;
  const selectedAction = LIVEPORTRAIT_ACTIONS.find((action) => action.id === selectedActionId) ?? LIVEPORTRAIT_ACTIONS[0];
  const selectedLtxPrompt = VIDEO_PROMPT_CHOICES.find((choice) => choice.id === videoPromptChoiceId) ?? VIDEO_PROMPT_CHOICES[0];
  const selectedVideoVendor = VIDEO_GENERATION_PROVIDERS.find((item) => item.id === videoVendor) ?? VIDEO_GENERATION_PROVIDERS[0];
  const availableVideoModels = VIDEO_GENERATION_MODELS.filter((model) => model.provider === videoVendor);
  const selectedVideoModel = VIDEO_GENERATION_MODELS.find((model) => model.id === ltxModel) ?? VIDEO_GENERATION_MODELS[0];
  const miniMaxResolutions: MiniMaxResolution[] = ltxModel === "MiniMax-H3-Max" ? ["480P", "768P"] : ["768P", "2K"];
  const miniMaxDurations = MINIMAX_DURATIONS.filter((duration) => duration === 6);
  const miniMaxImageRoleOptions = ltxModel === "MiniMax-H3-Max"
    ? MINIMAX_IMAGE_ROLE_OPTIONS.filter((option) => option.value !== "reference_image")
    : MINIMAX_IMAGE_ROLE_OPTIONS;
  const miniMaxUsesFrameRole = miniMaxImageRole !== "reference_image";
  const activeRuntime = provider === "ltx" ? ltxRuntime : livePortraitRuntime;
  const activeRuntimeMessage = provider === "ltx" ? ltxRuntimeMessage : livePortraitRuntimeMessage;
  const referencePreviewUrl = provider === "liveportrait"
    ? motionSourceMode === "template" ? selectedAction.referenceVideoUrl : drivingPreviewUrl
    : videoVendor === "minimax" ? miniMaxReferencePreviewUrl : "";
  const showingResult = previewMode === "result" && Boolean(resultUrl);
  const showingReference = previewMode === "reference" && Boolean(referencePreviewUrl);
  return (
    <section
      className={`${styles.studio} ${embedded ? styles.embedded : ""}`}
      aria-labelledby="action-studio-title"
      {...(embedded ? { "data-transition": "in-page" } : {})}
    >
      <header className={styles.intro}>
        <p>Avatar Action / LivePortrait + 视频生成</p>
        {!embedded ? <h1 id="action-studio-title">创建动作</h1> : null}
        <span>从当前 Avatar 源图生成可复用动作，并为所有已启用口型模型准备资产。</span>
      </header>

      <div className={styles.layout}>
        {!embedded ? <aside className={styles.sourcePanel}>
          <span>当前 Avatar 形象</span>
          <div className={styles.sourceImage}>
            {avatar ? <Image src={avatar.source_image_url} alt={avatar.display_name} fill sizes="280px" unoptimized /> : <LoaderCircle className={styles.spin} />}
          </div>
          <strong>{avatar?.display_name || "正在读取…"}</strong>
          <p>源图只读，新动作会归属于当前数字人。</p>
        </aside> : null}

        {(() => {
          const controlsPanel = (
          <div className={styles.controls}>
          {embedded && onChangeAvatar ? <section className={styles.selectedAvatarSummary} aria-label="数字人形象 · 当前共享 Avatar">
            <button type="button" aria-label={`预览 ${avatar?.display_name || avatarId}`} onClick={onPreviewAvatar}>
              {avatar ? <Image src={previewImageUrl || avatar.source_image_url} alt="" fill sizes="56px" unoptimized /> : <LoaderCircle className={styles.spin} />}
            </button>
            <span><strong>{avatar?.display_name || "正在读取…"}</strong></span>
            <button type="button" aria-label="上一步：返回选择 Avatar 形象" onClick={onChangeAvatar}><ArrowLeft aria-hidden="true" />上一步</button>
          </section> : null}
          <div className={styles.sectionHeading}>
            <h2 {...(embedded ? { id: "action-studio-title" } : {})}>{embedded ? "动作创作" : "动作来源"}</h2>
          </div>
          <div className={styles.enginePicker} role="tablist" aria-label="创建 Avatar 动作方式">
            <span className={styles.enginePickerTrack} data-provider={provider} aria-hidden="true" />
            <button type="button" role="tab" aria-selected={provider === "liveportrait"} data-active={provider === "liveportrait"} disabled={busy} onClick={() => selectProvider("liveportrait")}>
              <strong>LivePortrait</strong><small>动作迁移</small>
            </button>
            <button type="button" role="tab" aria-selected={provider === "ltx"} data-active={provider === "ltx"} disabled={busy} onClick={() => selectProvider("ltx")}>
              <strong>视频生成</strong><small>提示词驱动</small>
            </button>
          </div>
          {provider === "liveportrait" ? <>
          <div className={styles.actionSourcePicker} aria-label="动作来源">
            <div className={styles.actionSelect} ref={actionSelect} data-open={actionMenuOpen}>
              <button
                className={styles.actionSelectTrigger}
                type="button"
                role="combobox"
                aria-label="动作选项"
                aria-controls={actionListboxId}
                aria-expanded={actionMenuOpen}
                aria-haspopup="listbox"
                aria-activedescendant={actionMenuOpen ? `${actionListboxId}-${focusedActionId}` : undefined}
                disabled={busy}
                onClick={() => {
                  setFocusedActionId(selectedActionId);
                  setLtxPromptMenuOpen(false);
                  setVideoModelMenuOpen(false);
                  setActionMenuOpen((open) => !open);
                }}
                onKeyDown={handleActionPickerKeyDown}
              >
                <span className={styles.actionSelectValue}><strong>{selectedAction.name}</strong></span>
                <ChevronDown aria-hidden="true" />
              </button>
              <div className={styles.actionSelectMenu} id={actionListboxId} role="listbox" aria-label="内置动作选项" hidden={!actionMenuOpen}>
                {LIVEPORTRAIT_ACTIONS.map((action) => {
                  const unavailable = livePortraitRuntime === "ready" && !availableTemplates.has(action.id);
                  const selected = action.id === selectedActionId;
                  const focused = action.id === focusedActionId;
                  return (
                    <button
                      id={`${actionListboxId}-${action.id}`}
                      key={action.id}
                      type="button"
                      role="option"
                      aria-selected={selected}
                      data-focused={focused}
                      disabled={unavailable}
                      onPointerEnter={() => setFocusedActionId(action.id)}
                      onClick={() => selectTemplateAction(action.id)}
                    >
                      <span className={styles.actionOptionCopy}><strong>{action.name}</strong><small>{unavailable ? "当前素材不可用" : action.description}</small></span>
                      <span className={styles.actionOptionMeta}>{action.duration}</span>
                      <Check aria-hidden="true" />
                    </button>
                  );
                })}
              </div>
            </div>
            <div className={styles.uploadMotion} data-active={motionSourceMode === "upload"}>
              <button
                type="button"
                aria-label={drivingFile ? `上传动作，已选择 ${drivingFile.name}` : "上传动作"}
                aria-describedby={uploadMotionHintId}
                disabled={busy}
                onClick={() => drivingInput.current?.click()}
              >
                <Upload aria-hidden="true" />
                <span><strong>上传动作</strong></span>
              </button>
              {drivingFile ? <button type="button" aria-label="移除动作参考" disabled={busy} onClick={() => { setDrivingFile(null); setMotionSourceMode("template"); setActionName(selectedAction.name); setLivePortraitActionName(selectedAction.name); setPreviewMode("avatar"); setResultUrl(""); setSavedActionId(""); }}><X /></button> : null}
              <input ref={drivingInput} type="file" accept="video/mp4,video/webm,video/quicktime,.mov" onChange={(event) => selectDrivingFile(event.target.files?.[0])} />
              <span className={styles.uploadMotionHint} id={uploadMotionHintId} role="tooltip">MP4、WebM 或 MOV，最大 50MB</span>
            </div>
          </div>

          <fieldset className={styles.strengthField}>
            <legend><span>动作幅度</span><output>{motionMultiplier.toFixed(2)}×</output></legend>
            <div className={styles.strengthControl}>
              <input
                type="range"
                aria-label="动作幅度数值"
                min={MOTION_MULTIPLIER_MIN}
                max={MOTION_MULTIPLIER_MAX}
                step={0.01}
                value={motionMultiplier}
                disabled={busy}
                style={{ "--strength-progress": `${((motionMultiplier - MOTION_MULTIPLIER_MIN) / (MOTION_MULTIPLIER_MAX - MOTION_MULTIPLIER_MIN)) * 100}%` } as CSSProperties}
                onChange={(event) => updateMotionMultiplier(Number(event.target.value))}
              />
              <div className={styles.strengthPresets} aria-label="推荐动作幅度">
                {MOTION_STRENGTH_PRESETS.map((preset) => (
                  <button
                    key={preset.value}
                    type="button"
                    data-active={motionMultiplier === preset.value}
                    disabled={busy}
                    style={{ "--preset-position": `${((preset.value - MOTION_MULTIPLIER_MIN) / (MOTION_MULTIPLIER_MAX - MOTION_MULTIPLIER_MIN)) * 100}%` } as CSSProperties}
                    onClick={() => updateMotionMultiplier(preset.value)}
                  >
                    <strong>{preset.label}</strong>
                    <small>{preset.value.toFixed(2)}×</small>
                  </button>
                ))}
              </div>
            </div>
          </fieldset>
          </> : <div className={styles.ltxFields}>
            <div className={styles.videoProviderModelGrid}>
              <div className={styles.selectField}>
                <span>供应商</span>
                <div className={styles.actionSelect} ref={videoVendorSelect} data-open={videoVendorMenuOpen}>
                  <button
                    className={styles.actionSelectTrigger}
                    type="button"
                    role="combobox"
                    aria-label="视频生成供应商选择"
                    aria-controls={videoVendorListboxId}
                    aria-expanded={videoVendorMenuOpen}
                    aria-haspopup="listbox"
                    aria-activedescendant={videoVendorMenuOpen ? `${videoVendorListboxId}-${focusedVideoVendor}` : undefined}
                    disabled={busy}
                    onClick={() => {
                      setFocusedVideoVendor(videoVendor);
                      setVideoModelMenuOpen(false);
                      setLtxPromptMenuOpen(false);
                      setVideoVendorMenuOpen((open) => !open);
                    }}
                    onKeyDown={handleVideoVendorPickerKeyDown}
                  >
                    <span className={styles.actionSelectValue}><strong>{selectedVideoVendor.name}</strong><small>{selectedVideoVendor.detail}</small></span>
                    <ChevronDown aria-hidden="true" />
                  </button>
                  <div className={styles.actionSelectMenu} id={videoVendorListboxId} role="listbox" aria-label="视频生成供应商选项" hidden={!videoVendorMenuOpen}>
                    {VIDEO_GENERATION_PROVIDERS.map((item) => <button
                      id={`${videoVendorListboxId}-${item.id}`}
                      key={item.id}
                      type="button"
                      role="option"
                      aria-selected={item.id === videoVendor}
                      data-focused={item.id === focusedVideoVendor}
                      onPointerEnter={() => setFocusedVideoVendor(item.id)}
                      onClick={() => selectVideoVendor(item.id)}
                    >
                      <span className={styles.actionOptionCopy}><strong>{item.name}</strong><small>{item.detail}</small></span>
                      <Check aria-hidden="true" />
                    </button>)}
                  </div>
                </div>
              </div>
              <div className={styles.selectField}>
                <span>模型选择</span>
                <div className={styles.actionSelect} ref={videoModelSelect} data-open={videoModelMenuOpen}>
                <button
                  className={styles.actionSelectTrigger}
                  type="button"
                  role="combobox"
                  aria-label="视频生成模型选择"
                  aria-controls={videoModelListboxId}
                  aria-expanded={videoModelMenuOpen}
                  aria-haspopup="listbox"
                  aria-activedescendant={videoModelMenuOpen ? `${videoModelListboxId}-${focusedVideoModel}` : undefined}
                  disabled={busy}
                  onClick={() => {
                    setFocusedVideoModel(ltxModel);
                    setActionMenuOpen(false);
                    setLtxPromptMenuOpen(false);
                    setVideoVendorMenuOpen(false);
                    setVideoModelMenuOpen((open) => !open);
                  }}
                  onKeyDown={handleVideoModelPickerKeyDown}
                >
                  <span className={styles.actionSelectValue}><strong>{selectedVideoModel.name}</strong><small>{selectedVideoModel.detail}</small></span>
                  <ChevronDown aria-hidden="true" />
                </button>
                <div className={styles.actionSelectMenu} id={videoModelListboxId} role="listbox" aria-label="视频生成模型选项" hidden={!videoModelMenuOpen}>
                  {availableVideoModels.map((model) => {
                    const selected = model.id === ltxModel;
                    const focused = model.id === focusedVideoModel;
                    return (
                      <button
                        id={`${videoModelListboxId}-${model.id}`}
                        key={model.id}
                        type="button"
                        role="option"
                        aria-selected={selected}
                        data-focused={focused}
                        onPointerEnter={() => setFocusedVideoModel(model.id)}
                        onClick={() => selectVideoModel(model.id)}
                      >
                        <span className={styles.actionOptionCopy}><strong>{model.name}</strong><small>{model.detail}</small></span>
                        <Check aria-hidden="true" />
                      </button>
                    );
                  })}
                </div>
              </div>
              </div>
            </div>
            <div className={styles.promptChoiceField}>
              <span>提示词选择</span>
              <div className={styles.promptChoiceRow}>
                <div className={styles.actionSelect} ref={ltxPromptSelect} data-open={ltxPromptMenuOpen}>
                  <button
                    className={styles.actionSelectTrigger}
                    type="button"
                    role="combobox"
                    aria-label="视频生成提示词选择"
                    aria-controls={ltxPromptListboxId}
                    aria-expanded={ltxPromptMenuOpen}
                    aria-haspopup="listbox"
                    aria-activedescendant={ltxPromptMenuOpen ? `${ltxPromptListboxId}-${focusedVideoPromptChoiceId}` : undefined}
                    disabled={busy}
                    onClick={() => {
                      setFocusedVideoPromptChoiceId(videoPromptChoiceId);
                      setActionMenuOpen(false);
                      setVideoModelMenuOpen(false);
                      setVideoVendorMenuOpen(false);
                      setLtxPromptMenuOpen((open) => !open);
                    }}
                    onKeyDown={handleLtxPromptPickerKeyDown}
                  >
                    <span className={styles.actionSelectValue}><strong>{selectedLtxPrompt.name}</strong><small>{selectedLtxPrompt.description}</small></span>
                    <ChevronDown aria-hidden="true" />
                  </button>
                  <div className={styles.actionSelectMenu} id={ltxPromptListboxId} role="listbox" aria-label="视频生成提示词选项" hidden={!ltxPromptMenuOpen}>
                    {VIDEO_PROMPT_CHOICES.map((choice) => {
                      const selected = choice.id === videoPromptChoiceId;
                      const focused = choice.id === focusedVideoPromptChoiceId;
                      return (
                        <button
                          id={`${ltxPromptListboxId}-${choice.id}`}
                          key={choice.id}
                          type="button"
                          role="option"
                          aria-selected={selected}
                          data-focused={focused}
                          onPointerEnter={() => setFocusedVideoPromptChoiceId(choice.id)}
                          onClick={() => selectVideoPromptChoice(choice.id)}
                        >
                          <span className={styles.actionOptionCopy}><strong>{choice.name}</strong><small>{choice.description}</small></span>
                          <Check aria-hidden="true" />
                        </button>
                      );
                    })}
                  </div>
                </div>
                <button className={styles.promptViewButton} ref={promptViewButton} type="button" aria-label="查看当前视频生成提示词" onClick={() => setPromptModalOpen(true)}>
                  <Eye aria-hidden="true" />查看
                </button>
              </div>
            </div>
            {videoVendor === "minimax" ? <>
              <div className={styles.miniMaxParameterGrid}>
                <GenerationParameterSelect
                  label="数字人形象用途"
                  ariaLabel="数字人形象角色"
                  value={miniMaxImageRole}
                  disabled={busy}
                  options={miniMaxImageRoleOptions}
                  onChange={(value) => {
                  const nextRole = value as MiniMaxImageRole;
                  setMiniMaxImageRole(nextRole);
                  if (nextRole !== "reference_image") {
                    setMiniMaxRatio("adaptive");
                    setMiniMaxReferenceVideo(null);
                    setPreviewMode("avatar");
                  }
                  resetGeneratedPreview();
                }} />
                <GenerationParameterSelect
                  label="Ratio"
                  ariaLabel="MiniMax 画面比例"
                  value={miniMaxRatio}
                  disabled={busy}
                  options={MINIMAX_RATIOS.map((ratio) => ({ value: ratio, label: ratio === "adaptive" ? "自适应" : ratio }))}
                  onChange={(value) => {
                    const nextRatio = value as MiniMaxRatio;
                    setMiniMaxRatio(nextRatio);
                    resetGeneratedPreview();
                  }}
                />
                <GenerationParameterSelect
                  label="Resolution"
                  ariaLabel="MiniMax 分辨率"
                  value={miniMaxResolution}
                  disabled={busy}
                  options={miniMaxResolutions.map((resolution) => ({ value: resolution, label: resolution }))}
                  onChange={(value) => { setMiniMaxResolution(value as MiniMaxResolution); resetGeneratedPreview(); }}
                />
                <GenerationParameterSelect
                  label="Duration"
                  ariaLabel="MiniMax 时长"
                  value={String(miniMaxDuration)}
                  disabled={busy}
                  options={miniMaxDurations.map((duration) => ({ value: String(duration), label: `${duration} 秒` }))}
                  onChange={(value) => { setMiniMaxDuration(Number(value) as MiniMaxDuration); resetGeneratedPreview(); }}
                />
              </div>
              <p className={styles.miniMaxModeNote}>
                {ltxModel === "MiniMax-H3-Max"
                  ? "首帧 / 尾帧会先安全扩展到所选画幅，再由 H3 Max 按输入图片比例生成。"
                  : miniMaxUsesFrameRole
                    ? "首帧 / 尾帧会先安全扩展到所选画幅；人物完整保留，空白区域使用柔和背景延展。"
                    : "多模态参考模式可指定 Ratio；数字人形象使用 reference_image。"}
              </p>
              <div className={styles.miniMaxContent} aria-label="MiniMax 参考视频输入">
                <div className={styles.miniMaxVideoInput} data-active={Boolean(miniMaxReferenceVideo)}>
                  <button type="button" disabled={busy || ltxModel === "MiniMax-H3-Max"} aria-describedby={miniMaxUploadHintId} onClick={() => miniMaxReferenceInput.current?.click()}>
                    <Upload aria-hidden="true" /><span><strong>{miniMaxReferenceVideo ? miniMaxReferenceVideo.name : "上传参考视频"}</strong><small>固定 role · reference_video</small></span>
                  </button>
                  {miniMaxReferenceVideo ? <button type="button" aria-label="移除 MiniMax 参考视频" disabled={busy} onClick={() => { setMiniMaxReferenceVideo(null); setPreviewMode("avatar"); resetGeneratedPreview(); }}><X aria-hidden="true" /></button> : null}
                  <input ref={miniMaxReferenceInput} type="file" accept="video/mp4,video/quicktime,.mov" onChange={(event) => { selectMiniMaxReferenceVideo(event.target.files?.[0]); event.currentTarget.value = ""; }} />
                </div>
                <span id={miniMaxUploadHintId} className={styles.miniMaxUploadHint}>{ltxModel === "MiniMax-H3-Max" ? "H3 Max 不支持参考视频" : "MP4 / MOV，2–15 秒，最大 50MB；相同内容不会重复上传"}</span>
              </div>
              <p className={styles.costNote}>{ltxModel === "MiniMax-H3-Context-IR" ? "Context IR 会先增强提示词，再调用 H3 生成视频。" : ""} 首尾帧与多模态参考互斥；点击生成才会上传素材并消耗 MiniMax 额度。</p>
            </> : <p className={styles.costNote}>LTX 输出 720×1280 / 25 FPS；点击生成会消耗 LTX API 额度。</p>}
          </div>}
          {activeRuntime === "error" ? <div className={styles.notice}><CircleAlert /><span>{activeRuntimeMessage}</span><button type="button" onClick={() => void (provider === "ltx" ? checkLtxRuntime() : checkLivePortraitRuntime())}><RefreshCw />重试</button></div> : null}
          {error ? <div className={styles.notice} data-error><CircleAlert /><span>{error}</span></div> : null}
          <div className={styles.actionFooter} role="group" aria-label="动作名称与生成">
            <label className={styles.nameField}><span>动作名称</span><input value={actionName} maxLength={50} onChange={(event) => {
              setActionName(event.target.value);
              if (provider === "ltx") setLtxActionName(event.target.value);
              else setLivePortraitActionName(event.target.value);
            }} /></label>
            <button
              className={styles.generate}
              type="button"
              data-generate-action="true"
              aria-busy={busy}
              disabled={!avatar || !actionName.trim() || activeRuntime !== "ready" || busy || (provider === "ltx" ? !ltxPrompt.trim() : motionSourceMode === "upload" && !drivingFile)}
              onClick={() => void generatePreview()}
            >{busy ? <LoaderCircle className={styles.spin} aria-hidden="true" /> : null}{busy ? "生成中…" : "生成动作"}</button>
          </div>
        </div>
          );
          return embedded && onMobileConfigOpenChange ? (
            <StudioConfigOverlay
              open={Boolean(mobileConfigOpen)}
              onOpenChange={onMobileConfigOpenChange}
              label="动作配置"
              icon={<Wand2 aria-hidden="true" />}
            >
              {controlsPanel}
            </StudioConfigOverlay>
          ) : controlsPanel;
        })()}

        <aside className={styles.previewPanel} aria-label="动作效果预览" data-has-result={Boolean(resultUrl)} data-floating-preview="true">
          <div className={styles.previewFrame} data-preview-frame="true">
            {showingResult
              ? <video data-fit={previewFit} aria-label={`生成效果预览：${actionName}`} src={resultUrl} controls autoPlay muted loop playsInline onLoadedMetadata={(event) => setPreviewFit(classifyMediaAspectRatio(event.currentTarget.videoWidth, event.currentTarget.videoHeight))} />
              : showingReference
                ? <video key={referencePreviewUrl} data-fit={previewFit} aria-label={`参考动作预览：${provider === "ltx" ? miniMaxReferenceVideo?.name || "参考视频" : motionSourceMode === "template" ? selectedAction.name : "自定义动作"}`} src={referencePreviewUrl} controls autoPlay muted loop playsInline preload="metadata" onLoadedMetadata={(event) => setPreviewFit(classifyMediaAspectRatio(event.currentTarget.videoWidth, event.currentTarget.videoHeight))} />
                : avatar
                  ? <Image data-fit={previewFit} src={previewImageUrl || avatar.source_image_url} alt={`当前形象预览：${avatar.display_name}`} fill sizes="(max-width: 900px) 100vw, 70vw" unoptimized onLoad={(event) => setPreviewFit(classifyMediaAspectRatio(event.currentTarget.naturalWidth, event.currentTarget.naturalHeight))} />
                  : null}
            <div className={styles.previewChrome}>
              <div className={styles.previewTitle}>
                <span>{showingResult ? "生成效果" : showingReference ? "参考动作" : "当前形象"}</span>
                <strong>{showingResult ? actionName : showingReference ? provider === "ltx" ? miniMaxReferenceVideo?.name || "参考视频" : motionSourceMode === "template" ? selectedAction.name : drivingFile?.name || "自定义动作" : avatar?.display_name || "当前 Avatar"}</strong>
                {showingReference && provider === "liveportrait" && motionSourceMode === "template" && selectedAction.caution ? <em>{selectedAction.caution}</em> : null}
              </div>
              <div className={styles.previewModeSwitch} role="group" aria-label="预览内容">
                <button type="button" data-active={!showingReference && !showingResult} aria-pressed={!showingReference && !showingResult} disabled={!avatar} onClick={() => setPreviewMode("avatar")}>当前形象</button>
                <button type="button" data-active={showingReference} aria-pressed={showingReference} disabled={!referencePreviewUrl} onClick={() => setPreviewMode("reference")}>参考动作</button>
                <button type="button" data-active={showingResult} aria-pressed={showingResult} disabled={!resultUrl} onClick={() => setPreviewMode("result")}>生成效果</button>
              </div>
              {busy ? (
                <div className={styles.generationProgress} aria-label="视频生成进度">
                  <LoaderCircle className={styles.spin} aria-hidden="true" />
                  <div className={styles.generationProgressCopy}>
                    <strong role="status" aria-live="polite">{taskState === "queueing" ? "排队中…" : "视频生成中…"}</strong>
                    <span aria-live="off">已用时 {formatElapsedTime(elapsedMs)} · 请勿关闭或刷新此页面</span>
                  </div>
                  <div className={styles.generationProgressTrack} aria-hidden="true">
                    <span className={styles.generationProgressFill} style={{ "--progress": generationProgress } as CSSProperties} />
                  </div>
                </div>
              ) : (
                <div className={styles.previewActions}>
                  <button className={styles.accept} type="button" data-saved={Boolean(savedActionId)} disabled={!resultUrl || saving || Boolean(savedActionId)} onClick={() => void createActionAsset()}>
                    {saving ? <LoaderCircle className={styles.spin} /> : null}
                    {saving ? "正在创建并准备模型" : savedActionId ? "动作资产已创建" : "创建动作资产"}
                  </button>
                  {savedActionId ? <Link className={styles.viewAvatar} href={`/avatars/${encodeURIComponent(avatarId)}`}>查看 Avatar</Link> : null}
                </div>
              )}
            </div>
          </div>
        </aside>
      </div>
      {promptModalOpen ? <dialog
        ref={promptDialog}
        className={styles.promptModal}
        aria-labelledby="ltx-prompt-modal-title"
        onClose={() => {
          setPromptModalOpen(false);
          promptViewButton.current?.focus();
        }}
        onPointerDown={(event) => {
          if (event.target === event.currentTarget) closePromptModal();
        }}
      >
          <header>
            <span><small>VIDEO PROMPT</small><strong id="ltx-prompt-modal-title">{selectedLtxPrompt.name}</strong></span>
            <button type="button" aria-label="关闭提示词弹窗" autoFocus onClick={closePromptModal}><X aria-hidden="true" /></button>
          </header>
          <label>
            <span>完整提示词 <small>{ltxPrompt.length} / 5000</small></span>
            <textarea
              aria-label="视频生成弹窗提示词内容"
              value={ltxPrompt}
              maxLength={5000}
              rows={12}
              readOnly={videoPromptChoiceId !== "custom" || busy}
              onChange={(event) => {
                const nextPrompt = event.target.value;
                setLtxPrompt(nextPrompt);
                setCustomLtxPrompt(nextPrompt);
                setResultUrl("");
                setTaskId("");
                setTaskState("idle");
                setSavedActionId("");
              }}
            />
          </label>
          <footer>
            <span>{videoPromptChoiceId === "custom" ? "可直接编辑自定义提示词" : "预设提示词为只读内容"}</span>
            <button type="button" onClick={closePromptModal}>完成</button>
          </footer>
      </dialog> : null}
    </section>
  );
}

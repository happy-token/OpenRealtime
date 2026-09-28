"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";
import {
  Check,
  ChevronDown,
  CircleAlert,
  FileAudio,
  Mic,
  Pause,
  Pencil,
  Play,
  Plus,
  RotateCcw,
  Square,
  Trash2,
  Upload,
  UserRound,
  X,
} from "lucide-react";
import { mergeBailianClonedVoiceCatalog } from "@/lib/bailian-voice-clones";
import { readJsonResponse } from "@/lib/http-json-response";
import { BAILIAN_CLONED_VOICE_OPTIONS, BAILIAN_TTS_VOICE_OPTIONS, type TtsProvider } from "./voice-options";

interface ClonedVoice {
  id: string;
  displayName: string;
  status: "OK" | "UNDEPLOYED" | "UNKNOWN";
  createdAt: string | null;
}

interface VoiceClonePanelProps {
  provider: TtsProvider;
  selectedVoice: string;
  previewVoice: string | null;
  previewState: "idle" | "loading" | "playing";
  onSelect: (voiceId: string, label: string) => void;
  onPreview: (voiceId: string, label: string) => void;
  managementOnly?: boolean;
  embedded?: boolean;
  allowManagement?: boolean;
  onCatalogChange?: () => void;
  composerOpen?: boolean;
  onComposerOpenChange?: (open: boolean) => void;
  hideToolbar?: boolean;
  externalComposerTriggerRef?: RefObject<HTMLButtonElement | null>;
}

type SourceKind = "recording" | "upload";

export function canDeleteClonedVoice(voiceId: string, allowManagement: boolean) {
  return allowManagement
    && voiceId !== BAILIAN_CLONED_VOICE_OPTIONS[0].value;
}

export function canRepairMissingCloneSelection(catalogLoaded: boolean, catalogAvailable: boolean) {
  return catalogLoaded && catalogAvailable;
}

export function VoiceClonePanel({
  provider,
  selectedVoice,
  previewVoice,
  previewState,
  onSelect,
  onPreview,
  managementOnly = false,
  embedded = false,
  allowManagement = true,
  onCatalogChange,
  composerOpen: controlledComposerOpen,
  onComposerOpenChange,
  hideToolbar = false,
  externalComposerTriggerRef,
}: VoiceClonePanelProps) {
  const [voices, setVoices] = useState<ClonedVoice[]>([]);
  const [activeVoiceId, setActiveVoiceId] = useState<string | null>(null);
  const [catalogLoaded, setCatalogLoaded] = useState(false);
  const [catalogAvailable, setCatalogAvailable] = useState(false);
  const [configured, setConfigured] = useState(false);
  const [canCreate, setCanCreate] = useState(false);
  const [catalogNotice, setCatalogNotice] = useState("");
  const [localComposerOpen, setLocalComposerOpen] = useState(false);
  const [sourceKind, setSourceKind] = useState<SourceKind>("recording");
  const [displayName, setDisplayName] = useState("");
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [rightsConfirmed, setRightsConfirmed] = useState(false);
  const [recording, setRecording] = useState(false);
  const [recordingSeconds, setRecordingSeconds] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [submitNotice, setSubmitNotice] = useState("");
  const [editingVoiceId, setEditingVoiceId] = useState<string | null>(null);
  const [editingDisplayName, setEditingDisplayName] = useState("");
  const [pendingDeleteVoiceId, setPendingDeleteVoiceId] = useState<string | null>(null);
  const [managingVoiceId, setManagingVoiceId] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const recordingTimerRef = useRef<number | null>(null);
  const composerTriggerRef = useRef<HTMLButtonElement | null>(null);
  const composerDialogRef = useRef<HTMLDivElement | null>(null);
  const recordingRef = useRef(recording);
  const submittingRef = useRef(submitting);
  recordingRef.current = recording;
  submittingRef.current = submitting;
  const composerOpen = controlledComposerOpen ?? localComposerOpen;

  const updateComposerOpen = useCallback((next: boolean) => {
    if (controlledComposerOpen === undefined) setLocalComposerOpen(next);
    onComposerOpenChange?.(next);
  }, [controlledComposerOpen, onComposerOpenChange]);

  const loadVoices = useCallback(async () => {
    if (provider !== "bailian") return;
    setCatalogLoaded(false);
    try {
      const response = await fetch("/api/voice-clones", { cache: "no-store" });
      const payload = await readJsonResponse<{
        configured?: boolean;
        canCreate?: boolean;
        activeVoiceId?: string | null;
        voices?: ClonedVoice[];
        error?: string;
      }>(response, "克隆音色目录请求失败");
      setCatalogAvailable(!payload.error);
      setConfigured(Boolean(payload.configured));
      setCanCreate(Boolean(payload.canCreate));
      setActiveVoiceId(typeof payload.activeVoiceId === "string" ? payload.activeVoiceId : null);
      setVoices(Array.isArray(payload.voices) ? payload.voices : []);
      setCatalogNotice(payload.error || "");
    } catch {
      setConfigured(false);
      setCanCreate(false);
      setCatalogAvailable(false);
      setActiveVoiceId(null);
      setVoices([]);
      setCatalogNotice("克隆音色目录暂不可用");
    } finally {
      setCatalogLoaded(true);
    }
  }, [provider]);

  useEffect(() => {
    void loadVoices();
  }, [loadVoices]);

  useEffect(() => () => stopRecorderResources(), []);

  useEffect(() => {
    if (!pendingDeleteVoiceId) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !managingVoiceId) setPendingDeleteVoiceId(null);
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [managingVoiceId, pendingDeleteVoiceId]);

  useEffect(() => {
    if (!embedded || !composerOpen) return;
    const dialog = composerDialogRef.current;
    const trigger = externalComposerTriggerRef?.current ?? composerTriggerRef.current;
    const focusableSelector = 'button:not([disabled]),input:not([disabled]),[tabindex]:not([tabindex="-1"])';
    const initialFocus = dialog?.querySelector<HTMLElement>("[data-clone-initial-focus]")
      ?? dialog?.querySelector<HTMLElement>(focusableSelector);
    initialFocus?.focus();
    const keepFocusInside = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !submittingRef.current) {
        if (recordingRef.current) stopRecording();
        updateComposerOpen(false);
        return;
      }
      if (event.key !== "Tab" || !dialog) return;
      const focusable = Array.from(dialog.querySelectorAll<HTMLElement>(focusableSelector));
      if (!focusable.length) {
        event.preventDefault();
        dialog.focus();
        return;
      }
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
    document.addEventListener("keydown", keepFocusInside);
    return () => {
      document.removeEventListener("keydown", keepFocusInside);
      trigger?.focus();
    };
  }, [composerOpen, embedded, externalComposerTriggerRef, updateComposerOpen]);

  const displayedVoices = useMemo(() => {
    if (provider !== "bailian") return [];
    if (!activeVoiceId) return voices;
    const activeEnvironmentVoice: ClonedVoice = {
      id: activeVoiceId,
      displayName: BAILIAN_CLONED_VOICE_OPTIONS[0].label,
      status: "OK",
      createdAt: null,
    };
    return mergeBailianClonedVoiceCatalog(activeEnvironmentVoice, voices);
  }, [activeVoiceId, provider, voices]);
  const pendingDeleteVoice = displayedVoices.find((voice) => voice.id === pendingDeleteVoiceId) ?? null;

  useEffect(() => {
    const placeholderId = BAILIAN_CLONED_VOICE_OPTIONS[0].value;
    if (!canRepairMissingCloneSelection(catalogLoaded, catalogAvailable)
      || managementOnly
      || provider !== "bailian"
      || selectedVoice !== placeholderId) return;
    const activeVoice = displayedVoices.find((voice) => voice.id === activeVoiceId);
    if (activeVoiceId && activeVoice) {
      onSelect(activeVoiceId, activeVoice.displayName);
      return;
    }
    if (displayedVoices.some((voice) => voice.id === placeholderId)) return;
    const providerVoice = voices.find((voice) => (
      voice.displayName.trim().toLocaleLowerCase()
      === BAILIAN_CLONED_VOICE_OPTIONS[0].label.trim().toLocaleLowerCase()
    ));
    if (providerVoice) {
      onSelect(providerVoice.id, providerVoice.displayName);
      return;
    }
    onSelect(BAILIAN_TTS_VOICE_OPTIONS[0].value, BAILIAN_TTS_VOICE_OPTIONS[0].label);
  }, [activeVoiceId, catalogAvailable, catalogLoaded, displayedVoices, managementOnly, onSelect, provider, selectedVoice, voices]);

  async function startRecording() {
    setSubmitNotice("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      const mimeType = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus"]
        .find((candidate) => MediaRecorder.isTypeSupported(candidate));
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      streamRef.current = stream;
      recorderRef.current = recorder;
      chunksRef.current = [];
      setAudioFile(null);
      setRecordingSeconds(0);
      recorder.addEventListener("dataavailable", (event) => {
        if (event.data.size) chunksRef.current.push(event.data);
      });
      recorder.addEventListener("stop", () => {
        const blobType = recorder.mimeType || "audio/webm";
        const extension = blobType.startsWith("audio/ogg") ? "ogg" : "webm";
        const blob = new Blob(chunksRef.current, { type: blobType });
        setAudioFile(new File([blob], `voice-sample.${extension}`, { type: blobType }));
        setRecording(false);
        stopRecorderResources();
      }, { once: true });
      recorder.start(250);
      setRecording(true);
      recordingTimerRef.current = window.setInterval(() => {
        setRecordingSeconds((seconds) => {
          const next = seconds + 1;
          if (next >= 60) recorder.stop();
          return Math.min(next, 60);
        });
      }, 1000);
    } catch (error) {
      stopRecorderResources();
      setSubmitNotice(error instanceof DOMException && error.name === "NotAllowedError"
        ? "需要允许麦克风权限才能录制样本"
        : "无法启动录音，请检查麦克风设备");
    }
  }

  function stopRecording() {
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
  }

  function resetSample() {
    if (recording) stopRecording();
    setAudioFile(null);
    setRecordingSeconds(0);
    setSubmitNotice("");
  }

  async function submitClone() {
    if (!audioFile || !displayName.trim() || !rightsConfirmed || submitting) return;
    setSubmitting(true);
    setSubmitNotice("正在准备样本并创建克隆音色…");
    const form = new FormData();
    form.set("displayName", displayName.trim());
    form.set("sourceKind", sourceKind);
    form.set("rightsConfirmed", "true");
    form.set("audio", audioFile);
    try {
      const response = await fetch("/api/voice-clones", { method: "POST", body: form });
      const payload = await readJsonResponse<{ voice?: ClonedVoice; error?: string }>(
        response,
        "克隆音色创建请求失败",
      );
      if (!response.ok || !payload.voice) throw new Error(payload.error || "克隆音色创建失败");
      setVoices((current) => [payload.voice!, ...current.filter((voice) => voice.id !== payload.voice!.id)]);
      onSelect(payload.voice.id, payload.voice.displayName);
      onCatalogChange?.();
      updateComposerOpen(false);
      setDisplayName("");
      setRightsConfirmed(false);
      resetSample();
      setCatalogNotice(`“${payload.voice.displayName}”已创建并选中`);
    } catch (error) {
      setSubmitNotice(error instanceof Error ? error.message : "克隆音色创建失败");
    } finally {
      setSubmitting(false);
    }
  }

  async function renameVoice(voice: ClonedVoice) {
    const nextName = editingDisplayName.trim();
    if (!nextName || nextName === voice.displayName || managingVoiceId) {
      setEditingVoiceId(null);
      return;
    }
    setManagingVoiceId(voice.id);
    try {
      const response = await fetch("/api/voice-clones", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ voiceId: voice.id, displayName: nextName }),
      });
      const payload = await readJsonResponse<{ voice?: { id: string; displayName: string }; error?: string }>(
        response,
        "音色名称修改请求失败",
      );
      if (!response.ok || !payload.voice) throw new Error(payload.error || "音色名称修改失败");
      setVoices((current) => current.map((item) => item.id === voice.id ? { ...item, displayName: payload.voice!.displayName } : item));
      if (selectedVoice === voice.id) onSelect(voice.id, payload.voice.displayName);
      onCatalogChange?.();
      setEditingVoiceId(null);
      setCatalogNotice(`已将音色重命名为“${payload.voice.displayName}”`);
    } catch (error) {
      setCatalogNotice(error instanceof Error ? error.message : "音色名称修改失败");
    } finally {
      setManagingVoiceId(null);
    }
  }

  async function deleteVoice(voice: ClonedVoice) {
    if (managingVoiceId) return;
    setManagingVoiceId(voice.id);
    try {
      const response = await fetch("/api/voice-clones", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ voiceId: voice.id }),
      });
      const payload = await readJsonResponse<{ deleted?: boolean; error?: string }>(
        response,
        "克隆音色删除请求失败",
      );
      if (!response.ok || !payload.deleted) throw new Error(payload.error || "克隆音色删除失败");
      const remaining = voices.filter((item) => item.id !== voice.id);
      setVoices(remaining);
      if (selectedVoice === voice.id) {
        onSelect(BAILIAN_TTS_VOICE_OPTIONS[0].value, BAILIAN_TTS_VOICE_OPTIONS[0].label);
      }
      if (activeVoiceId === voice.id) setActiveVoiceId(null);
      onCatalogChange?.();
      setPendingDeleteVoiceId(null);
      setCatalogNotice(`“${voice.displayName}”已从百炼音色目录删除`);
    } catch (error) {
      setCatalogNotice(error instanceof Error ? error.message : "克隆音色删除失败");
    } finally {
      setManagingVoiceId(null);
    }
  }

  function stopRecorderResources() {
    if (recordingTimerRef.current !== null) window.clearInterval(recordingTimerRef.current);
    recordingTimerRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    recorderRef.current = null;
  }

  return (
    <details className="config-card voice-clone-card voice-library-disclosure" data-embedded={embedded} open={embedded || managementOnly || undefined}>
      <summary className="config-card-heading voice-clone-heading">
        <span className="config-step"><UserRound /></span>
        <div><h4>克隆音色</h4><p>{provider === "bailian" ? `${displayedVoices.length} 个可用音色` : "当前供应商暂未接入克隆接口"}</p></div>
        <ChevronDown className="voice-library-chevron" />
      </summary>

      {!hideToolbar ? <div className="voice-clone-toolbar">
        {embedded ? <span><strong>克隆音色</strong><small>{provider === "bailian" ? `${displayedVoices.length} 个可用音色` : "当前供应商暂未开放"}</small></span> : null}
        <button
          ref={composerTriggerRef}
          type="button"
          className="voice-clone-add"
          disabled={provider !== "bailian" || !canCreate}
          onClick={() => {
            if (composerOpen && recording) stopRecording();
            updateComposerOpen(!composerOpen);
            setSubmitNotice("");
          }}
        >
          {composerOpen ? <X /> : <Plus />}{composerOpen ? "关闭" : embedded ? "新建克隆" : "添加音色"}
        </button>
      </div> : null}

      {provider === "bailian" ? (
        <div className="voice-catalog-list cloned-voice-list" aria-label="克隆音色列表">
          {displayedVoices.map((voice) => {
            const selected = selectedVoice === voice.id;
            const previewing = previewVoice === voice.id;
            const isLoading = previewing && previewState === "loading";
            const isPlaying = previewing && previewState === "playing";
            const manageable = allowManagement && canCreate && voice.id !== BAILIAN_CLONED_VOICE_OPTIONS[0].value;
            const deletable = canCreate && canDeleteClonedVoice(voice.id, allowManagement);
            return <div className="provider-voice-row cloned-voice-row" data-selected={selected} key={voice.id}>
              {managementOnly ? <div className="provider-voice-select">
                <span className="provider-voice-avatar"><UserRound /></span>
                <span><strong title={voice.displayName}>{voice.displayName}</strong><small>{voice.status === "UNDEPLOYED" ? "部署中 · 暂不可用" : voice.createdAt ? `创建于 ${voice.createdAt}` : "当前运行环境"}</small></span>
              </div> : <button type="button" className="provider-voice-select" aria-pressed={selected} disabled={voice.status === "UNDEPLOYED"} onClick={() => onSelect(voice.id, voice.displayName)}>
                <span className="provider-voice-avatar">{selected ? <Check /> : <UserRound />}</span>
                <span><strong title={voice.displayName}>{voice.displayName}</strong><small>{voice.status === "UNDEPLOYED" ? "部署中 · 暂不可用" : selected ? `已选中 · ${voice.createdAt ? `创建于 ${voice.createdAt}` : "当前运行环境"}` : voice.createdAt ? `创建于 ${voice.createdAt}` : "当前运行环境"}</small></span>
              </button>}
              <div className="voice-clone-row-actions">
                {!managementOnly ? <button type="button" className="provider-voice-preview" aria-label={`${isPlaying ? "停止试听" : "试听"} ${voice.displayName}`} disabled={voice.status === "UNDEPLOYED" || (previewState === "loading" && !previewing)} onClick={() => onPreview(voice.id, voice.displayName)}>
                  {isLoading ? <span className="preview-spinner" /> : isPlaying ? <Square /> : <Play />}
                </button> : null}
                {manageable ? <button type="button" aria-label={`重命名 ${voice.displayName}`} title="重命名" onClick={() => { setEditingVoiceId(voice.id); setEditingDisplayName(voice.displayName); setPendingDeleteVoiceId(null); }}><Pencil /></button> : null}
                {deletable ? <button type="button" data-danger="true" aria-label={`删除 ${voice.displayName}`} title="删除" onClick={() => { setPendingDeleteVoiceId(voice.id); setEditingVoiceId(null); }}><Trash2 /></button> : null}
              </div>
              {editingVoiceId === voice.id ? <div className="voice-clone-inline-manager">
                <input value={editingDisplayName} maxLength={32} aria-label={`新的音色名称：${voice.displayName}`} autoFocus onChange={(event) => setEditingDisplayName(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void renameVoice(voice); if (event.key === "Escape") setEditingVoiceId(null); }} />
                <button type="button" disabled={!editingDisplayName.trim() || managingVoiceId === voice.id} onClick={() => void renameVoice(voice)}>保存</button>
                <button type="button" onClick={() => setEditingVoiceId(null)}>取消</button>
              </div> : null}
            </div>;
          })}
        </div>
      ) : (
        <div className="empty-cloned-voices"><CircleAlert /><span><strong>豆包 TTS 克隆暂未支持</strong><small>该能力按量收费，当前仅开放阿里云百炼克隆</small></span></div>
      )}

      {catalogNotice ? <p className="voice-clone-notice" role="status">{catalogNotice}</p> : null}
      {provider === "bailian" && catalogLoaded && !canCreate ? <p className="voice-clone-notice">新建克隆音色需要个人百炼 TTS 配置；平台 Key 不可用于克隆。</p> : null}

      {composerOpen && provider === "bailian" && canCreate ? (
        <ModalPortal enabled={embedded}>
        <div className={embedded ? "voice-clone-modal-backdrop" : undefined} onMouseDown={(event) => { if (embedded && event.target === event.currentTarget && !submitting) { if (recording) stopRecording(); updateComposerOpen(false); } }}>
        <div ref={composerDialogRef} className="voice-clone-composer" role={embedded ? "dialog" : undefined} aria-modal={embedded || undefined} aria-label={embedded ? "新建克隆音色" : undefined} tabIndex={embedded ? -1 : undefined}>
          {embedded ? <div className="voice-clone-composer-heading"><span><strong>新建克隆音色</strong></span><button type="button" aria-label="关闭新建克隆音色" disabled={submitting} onClick={() => { if (recording) stopRecording(); updateComposerOpen(false); }}><X /></button></div> : null}
          <div className="voice-clone-source-switch" role="tablist" aria-label="音色样本来源">
            <button type="button" role="tab" aria-selected={sourceKind === "recording"} data-active={sourceKind === "recording"} onClick={() => { setSourceKind("recording"); resetSample(); }}><Mic />直接录音</button>
            <button type="button" role="tab" aria-selected={sourceKind === "upload"} data-active={sourceKind === "upload"} onClick={() => { setSourceKind("upload"); resetSample(); }}><Upload />上传文件</button>
          </div>

          <label className="voice-clone-name"><span>音色名称</span><input data-clone-initial-focus value={displayName} maxLength={32} placeholder="例如：我的自然声线" onChange={(event) => setDisplayName(event.target.value)} /></label>

          <div className="voice-clone-script"><small>朗读参考</small><p>你好，这是我的音色样本。我会保持自然、稳定的语速，清晰地读完这段文字，让系统准确学习我的声音特点。</p></div>

          {sourceKind === "recording" ? (
            <div className="voice-recording-studio" data-recording={recording}>
              <div className="voice-recording-meter" aria-hidden="true">{Array.from({ length: 18 }, (_, index) => <i key={index} />)}</div>
              <strong>{recording ? "正在录制" : audioFile ? "录音已准备" : "录制 10–20 秒清晰语音"}</strong>
              <p>请在安静环境中使用正常语速，录制 10–20 秒清晰语音。</p>
              <div className="voice-recording-actions">
                {!recording && !audioFile ? <button type="button" onClick={() => void startRecording()}><Mic />开始录音</button> : null}
                {recording ? <button type="button" data-danger="true" onClick={stopRecording}><Pause />停止 · {formatSeconds(recordingSeconds)}</button> : null}
                {!recording && audioFile ? <span><FileAudio />{formatSeconds(recordingSeconds)} · {formatBytes(audioFile.size)}</span> : null}
                {!recording && audioFile ? <button type="button" onClick={resetSample}><RotateCcw />重新录制</button> : null}
              </div>
            </div>
          ) : (
            <label className="voice-clone-upload" data-ready={Boolean(audioFile)}>
              <Upload />
              <span><strong>{audioFile ? audioFile.name : "选择音频文件"}</strong><small>{audioFile ? formatBytes(audioFile.size) : "WAV / MP3 / M4A / WebM / OGG · 10MB 内"}</small></span>
              <input type="file" accept="audio/wav,audio/mpeg,audio/mp4,audio/webm,audio/ogg,.m4a" onChange={(event) => { setAudioFile(event.target.files?.[0] || null); setSubmitNotice(""); }} />
            </label>
          )}

          <label className="voice-clone-rights"><input type="checkbox" checked={rightsConfirmed} onChange={(event) => setRightsConfirmed(event.target.checked)} /><span>我确认已获得该声音的克隆和使用授权，且样本中不包含其他人的声音。</span></label>

          {submitNotice ? <p className="voice-clone-submit-notice" role="status"><CircleAlert />{submitNotice}</p> : null}
          {!configured ? <p className="voice-clone-submit-notice"><CircleAlert />服务端克隆凭据或公网样本存储尚未配置完整。</p> : null}
          <button type="button" className="voice-clone-submit" disabled={!configured || !canCreate || !audioFile || !displayName.trim() || !rightsConfirmed || submitting || (sourceKind === "recording" && recordingSeconds < 5)} onClick={() => void submitClone()}>
            {submitting ? <span className="preview-spinner" /> : <Plus />}{submitting ? "正在创建…" : "创建克隆音色"}
          </button>
        </div>
        </div>
        </ModalPortal>
      ) : null}

      {pendingDeleteVoice ? <ModalPortal enabled={embedded}><div className="avatar-asset-delete-dialog-backdrop" role="presentation" onMouseDown={(event) => {
        if (event.target === event.currentTarget && !managingVoiceId) setPendingDeleteVoiceId(null);
      }}>
        <section className="avatar-asset-delete-dialog" role="alertdialog" aria-modal="true" aria-labelledby="voice-clone-delete-title" aria-describedby="voice-clone-delete-description">
          <span className="avatar-asset-delete-dialog-icon"><CircleAlert /></span>
          <div><h3 id="voice-clone-delete-title">确认删除这个克隆音色？</h3></div>
          <p id="voice-clone-delete-description"><strong>{pendingDeleteVoice.displayName}</strong>删除后会同步从阿里云百炼音色目录移除，且无法恢复。{pendingDeleteVoice.id === activeVoiceId ? "该音色当前由运行环境指向，本页会切换到官方音色；服务端环境变量也需要同步更新。" : "当前配置中的引用将失效。"}</p>
          <div className="avatar-asset-delete-dialog-actions">
            <button type="button" autoFocus disabled={managingVoiceId === pendingDeleteVoice.id} onClick={() => setPendingDeleteVoiceId(null)}>取消</button>
            <button type="button" data-danger="true" disabled={managingVoiceId === pendingDeleteVoice.id} onClick={() => void deleteVoice(pendingDeleteVoice)}><Trash2 />{managingVoiceId === pendingDeleteVoice.id ? "正在删除…" : "确认删除"}</button>
          </div>
        </section>
      </div></ModalPortal> : null}
    </details>
  );
}

function ModalPortal({ enabled, children }: { enabled: boolean; children: ReactNode }) {
  return enabled && typeof document !== "undefined" ? createPortal(children, document.body) : children;
}

function formatSeconds(seconds: number) {
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function formatBytes(bytes: number) {
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

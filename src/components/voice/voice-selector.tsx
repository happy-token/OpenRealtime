"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AudioLines, Check, ChevronDown, Fingerprint, Languages, LoaderCircle, Mic2, Play, Plus, X } from "lucide-react";
import { VoiceClonePanel } from "@/components/drawer/voice-clone-panel";
import {
  BAILIAN_CLONED_VOICE_OPTIONS,
  BAILIAN_DIALECT_OPTIONS,
  BAILIAN_TTS_VOICE_OPTIONS,
  DEFAULT_TTS_VOICE,
  DIALECT_TTS_VOICE,
  TTS_DIALECT_OPTIONS,
  TTS_PROVIDER_OPTIONS,
  TTS_VOICE_OPTIONS,
  type TtsDialect,
  type TtsProvider,
} from "@/components/drawer/voice-options";
import { mergeBailianClonedVoiceCatalog, type BailianClonedVoice } from "@/lib/bailian-voice-clones";
import { readJsonResponse } from "@/lib/http-json-response";
import styles from "./voice-selector.module.css";

type VoiceModule = "provider" | "cloned" | "official" | "dialect";

export interface VoiceSelection {
  provider: TtsProvider;
  voice: string;
  dialect: TtsDialect;
}

export function describeVoiceSelection(value: VoiceSelection) {
  const voiceLabel = value.provider === "bailian"
    ? BAILIAN_TTS_VOICE_OPTIONS.find((item) => item.value === value.voice)?.label
      ?? (value.voice === BAILIAN_CLONED_VOICE_OPTIONS[0].value ? BAILIAN_CLONED_VOICE_OPTIONS[0].label : value.voice)
    : TTS_VOICE_OPTIONS.find((item) => item.value === value.voice)?.label ?? value.voice;
  const dialectLabel = value.dialect
    ? BAILIAN_DIALECT_OPTIONS.find((item) => item.value === value.dialect)?.label
    : null;
  return `${voiceLabel}${dialectLabel ? ` · ${dialectLabel}` : ""}`;
}

interface VoiceSelectorProps {
  value: VoiceSelection;
  onChange: (selection: VoiceSelection) => void;
  onSelectionCommit?: () => void;
  allowClone?: boolean;
  allowManagement?: boolean;
  showCurrent?: boolean;
  currentLabel?: string;
}

export function VoiceSelector({
  value,
  onChange,
  onSelectionCommit,
  allowClone = true,
  allowManagement = false,
  showCurrent = true,
  currentLabel = "当前声音",
}: VoiceSelectorProps) {
  const [openModule, setOpenModule] = useState<VoiceModule | null>(null);
  const [cloneComposerOpen, setCloneComposerOpen] = useState(false);
  const [clonedVoices, setClonedVoices] = useState<BailianClonedVoice[]>([]);
  const [activeCloneId, setActiveCloneId] = useState<string | null>(null);
  const [previewVoice, setPreviewVoice] = useState<string | null>(null);
  const [previewState, setPreviewState] = useState<"idle" | "loading" | "playing">("idle");
  const [previewNotice, setPreviewNotice] = useState("");
  const previewAudioRef = useRef<HTMLAudioElement | null>(null);
  const previewUrlRef = useRef("");
  const previewRequestRef = useRef<AbortController | null>(null);
  const cloneComposerTriggerRef = useRef<HTMLButtonElement | null>(null);

  const loadClones = useCallback(async (signal?: AbortSignal) => {
    try {
      const response = await fetch("/api/voice-clones", { cache: "no-store", signal });
      const payload = await readJsonResponse<{ activeVoiceId?: string | null; voices?: BailianClonedVoice[] }>(response, "克隆音色目录请求失败");
      if (signal?.aborted) return;
      setActiveCloneId(typeof payload.activeVoiceId === "string" ? payload.activeVoiceId : null);
      setClonedVoices(Array.isArray(payload.voices) ? payload.voices : []);
    } catch {
      if (!signal?.aborted) {
        setActiveCloneId(null);
        setClonedVoices([]);
      }
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void loadClones(controller.signal);
    return () => controller.abort();
  }, [loadClones]);

  useEffect(() => () => {
    previewRequestRef.current?.abort();
    previewAudioRef.current?.pause();
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
  }, []);

  const clones = useMemo(() => activeCloneId ? mergeBailianClonedVoiceCatalog({
    id: activeCloneId,
    displayName: BAILIAN_CLONED_VOICE_OPTIONS[0].label,
    status: "OK",
    createdAt: null,
  }, clonedVoices) : clonedVoices, [activeCloneId, clonedVoices]);
  const officialVoices = value.provider === "bailian" ? BAILIAN_TTS_VOICE_OPTIONS : TTS_VOICE_OPTIONS;
  const dialects = (value.provider === "bailian" ? BAILIAN_DIALECT_OPTIONS : TTS_DIALECT_OPTIONS).filter((item) => item.value);
  const currentVoiceLabel = value.provider === "bailian"
    ? BAILIAN_TTS_VOICE_OPTIONS.find((item) => item.value === value.voice)?.label
      ?? clones.find((item) => item.id === value.voice)?.displayName
      ?? (value.voice === BAILIAN_CLONED_VOICE_OPTIONS[0].value ? BAILIAN_CLONED_VOICE_OPTIONS[0].label : value.voice)
    : TTS_VOICE_OPTIONS.find((item) => item.value === value.voice)?.label ?? value.voice;
  const currentDialectLabel = value.dialect
    ? BAILIAN_DIALECT_OPTIONS.find((item) => item.value === value.dialect)?.label
    : null;

  function stopVoicePreview(message = "") {
    previewRequestRef.current?.abort();
    previewRequestRef.current = null;
    previewAudioRef.current?.pause();
    previewAudioRef.current = null;
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    previewUrlRef.current = "";
    setPreviewVoice(null);
    setPreviewState("idle");
    setPreviewNotice(message);
  }

  function commit(selection: VoiceSelection) {
    stopVoicePreview();
    onChange(selection);
    setOpenModule(null);
    onSelectionCommit?.();
  }

  function selectProvider(provider: TtsProvider) {
    stopVoicePreview();
    if (provider !== value.provider) onChange({
      provider,
      voice: provider === "bailian" ? BAILIAN_TTS_VOICE_OPTIONS[0].value : DEFAULT_TTS_VOICE,
      dialect: "",
    });
    setOpenModule(null);
  }

  function selectDialect(dialect: TtsDialect) {
    const voice = value.provider === "bailian" ? "longanhuan_v3" : DIALECT_TTS_VOICE;
    commit({ provider: value.provider, voice, dialect });
  }

  async function toggleVoicePreview(provider: TtsProvider, voice: string, label: string, dialect: TtsDialect = "") {
    const previewKey = dialect ? `${voice}:${dialect}` : voice;
    if (previewVoice === previewKey && previewState === "playing") {
      stopVoicePreview("已停止试听");
      return;
    }
    stopVoicePreview();
    setPreviewVoice(previewKey);
    setPreviewState("loading");
    setPreviewNotice(`正在生成「${label}」试听…`);
    const controller = new AbortController();
    previewRequestRef.current = controller;
    try {
      const params = new URLSearchParams({ provider, voice, speech_rate: "0", dialect });
      const response = await fetch(`/api/tts/preview?${params.toString()}`, { signal: controller.signal });
      if (!response.ok) {
        const payload = await response.json().catch(() => null) as { error?: string } | null;
        throw new Error(payload?.error ?? "音色试听生成失败");
      }
      const blob = await response.blob();
      if (controller.signal.aborted) return;
      if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
      const url = URL.createObjectURL(blob);
      previewUrlRef.current = url;
      const audio = new Audio(url);
      previewAudioRef.current = audio;
      audio.onended = () => stopVoicePreview("试听结束");
      audio.onerror = () => stopVoicePreview("音频播放失败，请稍后重试");
      await audio.play();
      if (controller.signal.aborted || previewAudioRef.current !== audio) {
        audio.pause();
        return;
      }
      previewRequestRef.current = null;
      setPreviewState("playing");
      setPreviewNotice(`正在播放「${label}」`);
    } catch (cause) {
      if (!controller.signal.aborted) stopVoicePreview(cause instanceof Error ? cause.message : "音色试听生成失败");
    }
  }

  function toggleModule(module: VoiceModule) {
    stopVoicePreview();
    setOpenModule((current) => current === module ? null : module);
  }

  return <div className={styles.selector}>
    {showCurrent ? <div className={styles.current} aria-live="polite">
      <span className={styles.currentIcon}><Mic2 aria-hidden="true" /></span>
      <div><small>{currentLabel}</small><strong>{currentVoiceLabel}{currentDialectLabel ? ` · ${currentDialectLabel}` : ""}</strong></div>
      <em>{TTS_PROVIDER_OPTIONS.find((item) => item.value === value.provider)?.label}</em>
    </div> : null}
    <div className={styles.moduleList}>
      <VoiceModuleRow icon={<AudioLines />} title="供应商选择" detail={`${TTS_PROVIDER_OPTIONS.find((item) => item.value === value.provider)?.label} · 后续供应商继续加入此列表`} open={openModule === "provider"} onToggle={() => toggleModule("provider")}>
        <div className={styles.providerList} aria-label="声音供应商">{TTS_PROVIDER_OPTIONS.map((item) => <button key={item.value} type="button" aria-pressed={value.provider === item.value} onClick={() => selectProvider(item.value)}><span><strong>{item.label}</strong><small>{item.description}</small></span>{value.provider === item.value ? <Check /> : null}</button>)}</div>
      </VoiceModuleRow>

      {allowClone ? <VoiceModuleRow icon={<Fingerprint />} title="音色克隆" detail={value.provider === "bailian" ? "支持试听、克隆和已有音色选择" : "当前供应商暂不支持音色克隆"} open={openModule === "cloned"} onToggle={() => toggleModule("cloned")} action={<button ref={cloneComposerTriggerRef} className={styles.moduleAction} type="button" disabled={value.provider !== "bailian"} onClick={() => { stopVoicePreview(); setOpenModule("cloned"); setCloneComposerOpen(true); }}><Plus />新建克隆音色</button>}>
        <div className={styles.cloneLibrary}><VoiceClonePanel embedded hideToolbar allowManagement={allowManagement} provider={value.provider} selectedVoice={value.provider === "bailian" && !value.dialect ? value.voice : ""} previewVoice={previewVoice} previewState={previewState} composerOpen={cloneComposerOpen} onComposerOpenChange={setCloneComposerOpen} externalComposerTriggerRef={cloneComposerTriggerRef} onSelect={(voiceId, label) => { onChange({ provider: "bailian", voice: voiceId, dialect: "" }); setClonedVoices((items) => [{ id: voiceId, displayName: label, status: "OK", createdAt: null }, ...items.filter((item) => item.id !== voiceId)]); setOpenModule(null); onSelectionCommit?.(); }} onPreview={(voiceId, label) => void toggleVoicePreview("bailian", voiceId, label)} onCatalogChange={() => void loadClones()} /></div>
      </VoiceModuleRow> : null}

      <VoiceModuleRow icon={<AudioLines />} title="官方音色" detail={`${officialVoices.length} 个当前供应商音色 · 支持试听`} open={openModule === "official"} onToggle={() => toggleModule("official")}>
        <div className={styles.choiceList} aria-label="官方音色">{officialVoices.map((item) => {
          const selected = value.voice === item.value && !value.dialect;
          const previewing = previewVoice === item.value;
          return <div className={styles.voiceOption} data-selected={selected} key={item.value}><button className={styles.voiceSelect} type="button" aria-pressed={selected} onClick={() => commit({ provider: value.provider, voice: item.value, dialect: "" })}><span><strong>{item.label}</strong><small>{item.description}</small></span>{selected ? <Check /> : null}</button><button className={styles.previewButton} type="button" aria-label={`${previewing && previewState === "playing" ? "停止试听" : "试听"} ${item.label}`} disabled={previewState === "loading" && !previewing} onClick={() => void toggleVoicePreview(value.provider, item.value, item.label)}>{previewing && previewState === "loading" ? <LoaderCircle className={styles.spin} /> : previewing && previewState === "playing" ? <X /> : <Play />}</button></div>;
        })}</div>
      </VoiceModuleRow>

      <VoiceModuleRow icon={<Languages />} title="方言支持" detail={`${dialects.length} 种当前供应商方言 · 支持试听`} open={openModule === "dialect"} onToggle={() => toggleModule("dialect")}>
        <div className={styles.choiceList} aria-label="方言">{dialects.map((item) => {
          const voice = value.provider === "bailian" ? "longanhuan_v3" : DIALECT_TTS_VOICE;
          const previewing = previewVoice === `${voice}:${item.value}`;
          const selected = value.dialect === item.value;
          return <div className={styles.voiceOption} data-selected={selected} key={item.value}><button className={styles.voiceSelect} type="button" aria-pressed={selected} onClick={() => selectDialect(item.value)}><span><strong>{item.label}</strong><small>{item.description}</small></span>{selected ? <Check /> : null}</button><button className={styles.previewButton} type="button" aria-label={`${previewing && previewState === "playing" ? "停止试听" : "试听"} ${item.label}`} disabled={previewState === "loading" && !previewing} onClick={() => void toggleVoicePreview(value.provider, voice, item.label, item.value)}>{previewing && previewState === "loading" ? <LoaderCircle className={styles.spin} /> : previewing && previewState === "playing" ? <X /> : <Play />}</button></div>;
        })}</div>
      </VoiceModuleRow>
    </div>
    {previewNotice ? <p className={styles.notice} role="status">{previewNotice}</p> : null}
  </div>;
}

function VoiceModuleRow({ icon, title, detail, open, onToggle, action, children }: { icon: React.ReactNode; title: string; detail: string; open: boolean; onToggle: () => void; action?: React.ReactNode; children: React.ReactNode }) {
  return <section className={styles.module} data-open={open}><div className={styles.moduleHeader}><button className={styles.moduleToggle} type="button" aria-expanded={open} onClick={onToggle}><span className={styles.moduleIcon}>{icon}</span><span className={styles.moduleCopy}><strong>{title}</strong><small>{detail}</small></span><ChevronDown /></button>{action}</div>{open ? <div className={styles.moduleContent}>{children}</div> : null}</section>;
}

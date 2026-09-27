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
import type { ProviderInstance } from "@/lib/provider-instances";
import type { PlatformProviderCredential } from "@/lib/platform-provider-credentials";
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
  roleId?: string;
  configurationTarget?: string | null;
  onConfigurationChange?: (target: string | null) => void;
}

type TtsConfiguration = { target: string; name: string; provider: "doubao" | "dashscope";
  scope: "personal" | "platform"; selectable: boolean; updatedAt?: string };

export function VoiceSelector({
  value,
  onChange,
  onSelectionCommit,
  allowClone = true,
  allowManagement = false,
  showCurrent = true,
  currentLabel = "当前声音",
  roleId,
  configurationTarget,
  onConfigurationChange,
}: VoiceSelectorProps) {
  const [openModule, setOpenModule] = useState<VoiceModule | null>(null);
  const [cloneComposerOpen, setCloneComposerOpen] = useState(false);
  const [clonedVoices, setClonedVoices] = useState<BailianClonedVoice[]>([]);
  const [activeCloneId, setActiveCloneId] = useState<string | null>(null);
  const [canCreateClone, setCanCreateClone] = useState(false);
  const [configurations, setConfigurations] = useState<TtsConfiguration[]>([]);
  const [defaultTtsTarget, setDefaultTtsTarget] = useState<string | null>(null);
  const [selectedConfiguration, setSelectedConfiguration] = useState<string | null>(configurationTarget ?? null);
  const [configurationLoading, setConfigurationLoading] = useState(true);
  const [configurationBusy, setConfigurationBusy] = useState(false);
  const [configurationError, setConfigurationError] = useState("");
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
      const payload = await readJsonResponse<{ activeVoiceId?: string | null; voices?: BailianClonedVoice[]; canCreate?: boolean }>(response, "克隆音色目录请求失败");
      if (signal?.aborted) return;
      setActiveCloneId(typeof payload.activeVoiceId === "string" ? payload.activeVoiceId : null);
      setCanCreateClone(Boolean(payload.canCreate));
      setClonedVoices(Array.isArray(payload.voices) ? payload.voices : []);
    } catch {
      if (!signal?.aborted) {
        setActiveCloneId(null);
        setCanCreateClone(false);
        setClonedVoices([]);
      }
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void loadClones(controller.signal);
    return () => controller.abort();
  }, [loadClones]);

  useEffect(() => { if (!roleId) setSelectedConfiguration(configurationTarget ?? null); }, [configurationTarget, roleId]);
  useEffect(() => {
    const controller = new AbortController();
    setConfigurationLoading(true);
    void Promise.all([
      fetch("/api/provider-instances", { cache: "no-store", signal: controller.signal })
        .then(async (response) => response.ok ? await response.json() as {
          instances?: ProviderInstance[]; platformCredentials?: PlatformProviderCredential[];
          selections?: { tts?: string }; platformSelections?: { tts?: string };
        } : null),
      roleId ? fetch(`/api/user/role-tts-selections/${encodeURIComponent(roleId)}`, { cache: "no-store", signal: controller.signal })
        .then(async (response) => response.ok ? await response.json() as { target?: string | null } : null) : Promise.resolve(null),
    ]).then(([catalog, saved]) => {
      if (controller.signal.aborted) return;
      const instances = catalog?.instances?.filter((instance) => instance.capability === "tts"
        && (instance.provider === "doubao" || instance.provider === "dashscope")) ?? [];
      const configured: TtsConfiguration[] = instances.map((instance) => ({ target: instance.id,
        name: instance.displayName, provider: instance.provider as "doubao" | "dashscope", scope: instance.scope,
        selectable: instance.enabled && instance.connectionStatus === "passed", updatedAt: instance.updatedAt }));
      for (const credential of catalog?.platformCredentials ?? []) {
        if (credential.capability !== "tts" || (credential.provider !== "doubao" && credential.provider !== "dashscope")) continue;
        configured.push({ target: `env:${credential.provider}`, name: credential.name,
          provider: credential.provider, scope: "platform", selectable: true });
      }
      setConfigurations(configured);
      setDefaultTtsTarget(catalog?.selections?.tts ?? catalog?.platformSelections?.tts ?? null);
      if (roleId) setSelectedConfiguration(saved?.target ?? null);
      setConfigurationError(catalog ? "" : "配置列表暂不可用，请稍后重试");
    }).catch(() => { if (!controller.signal.aborted) setConfigurationError("配置列表暂不可用，请稍后重试"); })
      .finally(() => { if (!controller.signal.aborted) setConfigurationLoading(false); });
    return () => controller.abort();
  }, [roleId]);

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
  const currentProviderId = value.provider === "bailian" ? "dashscope" : "doubao";
  const defaultConfiguration = configurations.find((item) => item.target === defaultTtsTarget && item.selectable);
  const matchingConfigurations = configurations.filter((item) => item.provider === currentProviderId && item.selectable);
  const compatibleConfiguration = matchingConfigurations.filter((item) => !item.target.startsWith("env:"))
    .sort((left, right) => (left.scope === right.scope ? (right.updatedAt ?? "").localeCompare(left.updatedAt ?? "")
      : left.scope === "personal" ? -1 : 1))[0]
    ?? matchingConfigurations.find((item) => item.target.startsWith("env:"));
  const displayedTarget = selectedConfiguration ?? defaultConfiguration?.target ?? compatibleConfiguration?.target ?? null;
  const displayedConfiguration = configurations.find((item) => item.target === displayedTarget);

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

  async function selectConfiguration(configuration: TtsConfiguration) {
    if (!configuration.selectable || configurationBusy) return;
    setConfigurationBusy(true);
    setConfigurationError("");
    try {
      if (roleId) {
        const response = await fetch(`/api/user/role-tts-selections/${encodeURIComponent(roleId)}`, {
          method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ target: configuration.target }),
        });
        const result = await readJsonResponse<{ error?: string }>(response, "保存角色语音配置失败");
        if (!response.ok) throw new Error(result.error || "保存角色语音配置失败");
      }
      setSelectedConfiguration(configuration.target);
      onConfigurationChange?.(configuration.target);
      selectProvider(configuration.provider === "dashscope" ? "bailian" : "doubao");
    } catch (error) {
      setConfigurationError(error instanceof Error ? error.message : "保存角色语音配置失败");
    } finally { setConfigurationBusy(false); }
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
      <VoiceModuleRow icon={<AudioLines />} title="供应商选择" detail={displayedConfiguration
        ? `${displayedConfiguration.name} · ${displayedConfiguration.scope === "personal" ? "个人配置" : "平台配置"}${selectedConfiguration ? "" : " · 自动匹配"}`
        : selectedConfiguration ? "已选配置不可用" : `${TTS_PROVIDER_OPTIONS.find((item) => item.value === value.provider)?.label} · 暂无可用配置`} open={openModule === "provider"} onToggle={() => toggleModule("provider")}>
        <div className={styles.providerList} aria-label="声音供应商">
          {configurationLoading ? <p className={styles.notice}>正在读取配置…</p> : [...configurations]
            .sort((left, right) => left.scope === right.scope ? 0 : left.scope === "platform" ? -1 : 1)
            .map((item) => <button key={item.target} type="button" aria-pressed={displayedTarget === item.target}
                disabled={!item.selectable || configurationBusy} onClick={() => void selectConfiguration(item)}>
                <span><strong>{item.name}</strong><small>{item.provider === "dashscope" ? "阿里云百炼" : "火山引擎"} · {item.scope === "personal" ? "个人配置" : "平台配置"}{item.selectable ? "" : " · 请先测试"}</small></span>
                {displayedTarget === item.target ? <Check /> : null}</button>)}
          {!configurationLoading && configurations.length === 0 ? <p className={styles.notice}>暂无可用 TTS 配置，请先到供应商页面添加。</p> : null}
        </div>
        {configurationError ? <p className={styles.notice} role="alert">{configurationError}</p> : null}
      </VoiceModuleRow>
      {allowClone ? <VoiceModuleRow icon={<Fingerprint />} title="音色克隆" detail={value.provider !== "bailian" ? "当前音色来源暂不支持克隆" : canCreateClone ? "可使用个人配置创建克隆音色" : "仅个人百炼配置可创建，平台配置不可克隆"} open={openModule === "cloned"} onToggle={() => toggleModule("cloned")} action={<button ref={cloneComposerTriggerRef} className={styles.moduleAction} type="button" disabled={value.provider !== "bailian" || !canCreateClone} onClick={() => { stopVoicePreview(); setOpenModule("cloned"); setCloneComposerOpen(true); }}><Plus />新建克隆音色</button>}>
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

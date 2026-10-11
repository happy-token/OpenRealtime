"use client";
import { LocalizedText } from "@/components/language/language-provider";

import { useLanguage } from "@/components/language/language-provider";


import { useEffect, useMemo, useRef, useState } from "react";
import {
  DIALECT_TTS_VOICE,
  TTS_VOICE_OPTIONS,
  findTtsVoice,
  isTtsVoice,
  type TtsDialect,
  type TtsVoice,
} from "@/components/drawer/voice-options";

interface VoicePickerModalProps {
  open: boolean;
  value: TtsVoice;
  speechRate: number;
  dialect: TtsDialect;
  previewAvailable: boolean;
  playbackVolume: number;
  onClose: () => void;
  onConfirm: (voice: TtsVoice) => void;
}

function voiceCategory(description?: string) {
  return description?.split(" · ")[0] ?? "自定义";
}

export function VoicePickerModal({
  open,
  value,
  speechRate,
  dialect,
  previewAvailable,
  playbackVolume,
  onClose,
  onConfirm,
}: VoicePickerModalProps) {
  const { t } = useLanguage();
  const [draftVoice, setDraftVoice] = useState<TtsVoice>(value);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("全部");
  const [previewVoice, setPreviewVoice] = useState<string | null>(null);
  const [previewState, setPreviewState] = useState<"idle" | "loading" | "playing">("idle");
  const [previewNotice, setPreviewNotice] = useState("");
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioUrlRef = useRef("");

  const categories = useMemo(
    () => ["全部", ...Array.from(new Set(TTS_VOICE_OPTIONS.map((voice) => voiceCategory(voice.description))))],
    [],
  );

  const normalizedQuery = query.trim().toLocaleLowerCase();
  const filteredVoices = TTS_VOICE_OPTIONS.filter((voice) => {
    const matchesCategory = category === "全部" || voiceCategory(voice.description) === category;
    const matchesQuery = !normalizedQuery || `${voice.label} ${voice.description} ${voice.value}`
      .toLocaleLowerCase()
      .includes(normalizedQuery);
    return matchesCategory && matchesQuery;
  });
  const customVoice = query.trim();
  const showCustomVoice = Boolean(
    normalizedQuery
      && isTtsVoice(customVoice)
      && !findTtsVoice(customVoice),
  );
  const draftLabel = findTtsVoice(draftVoice)?.label ?? "自定义音色";

  useEffect(() => {
    if (!open) return;
    setDraftVoice(value);
    setQuery("");
    setCategory("全部");
    setPreviewNotice("");
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose, open, value]);

  useEffect(() => {
    if (audioRef.current) audioRef.current.volume = playbackVolume / 100;
  }, [playbackVolume]);

  useEffect(() => () => {
    audioRef.current?.pause();
    if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current);
  }, []);

  function stopPreview(notice = "") {
    audioRef.current?.pause();
    audioRef.current = null;
    setPreviewVoice(null);
    setPreviewState("idle");
    setPreviewNotice(notice);
  }

  async function preview(voice: TtsVoice) {
    if (previewState === "playing" && previewVoice === voice) {
      stopPreview("已停止试听");
      return;
    }
    stopPreview();
    setPreviewVoice(voice);
    setPreviewState("loading");
    setPreviewNotice("正在生成试听…");
    try {
      const params = new URLSearchParams({
        voice,
        speech_rate: String(speechRate),
        dialect: voice === DIALECT_TTS_VOICE ? dialect : "",
      });
      const response = await fetch(`/api/tts/preview?${params.toString()}`);
      if (!response.ok) {
        const payload = await response.json().catch(() => null) as { error?: string } | null;
        throw new Error(payload?.error ?? "该音色暂不可用");
      }
      const blob = await response.blob();
      if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current);
      const url = URL.createObjectURL(blob);
      audioUrlRef.current = url;
      const audio = new Audio(url);
      audio.volume = playbackVolume / 100;
      audioRef.current = audio;
      audio.onended = () => stopPreview("试听结束");
      audio.onerror = () => stopPreview("音频播放失败，请稍后重试");
      await audio.play();
      setPreviewState("playing");
      setPreviewNotice("正在播放试听");
    } catch (error) {
      stopPreview(error instanceof Error ? error.message : "该音色暂不可用");
    }
  }

  if (!open) return null;

  const renderVoice = (voice: { value: TtsVoice; label: string; description?: string }) => {
    const selected = voice.value === draftVoice;
    const previewing = previewVoice === voice.value;
    return (
      <div className="voice-picker-card" data-selected={selected} key={voice.value}>
        <button
          type="button"
          className="voice-picker-card-select"
          aria-pressed={selected}
          onClick={() => setDraftVoice(voice.value)}
        >
          <span className="voice-picker-avatar" aria-hidden="true">{voice.label.slice(0, 1)}</span>
          <span className="voice-picker-card-copy">
            <strong>{<LocalizedText text={voice.label} />}</strong>
            <small>{voice.description ?? voice.value}</small>
          </span>
          <span className="voice-picker-check" aria-hidden="true">{selected ? "✓" : ""}</span>
        </button>
        <button
          type="button"
          className="voice-picker-preview"
          aria-label={previewing && previewState === "playing" ? t("停止试听 ") + (voice.label) + "" : t("试听 ") + (voice.label) + ""}
          disabled={!previewAvailable || (previewState === "loading" && !previewing)}
          data-state={previewing ? previewState : "idle"}
          onClick={() => preview(voice.value)}
        >
          {previewing && previewState === "loading" ? (
            <span className="preview-spinner" />
          ) : (
            <svg viewBox="0 0 20 20" aria-hidden="true">
              <path d={previewing && previewState === "playing" ? "M6.5 6.5h7v7h-7z" : "m7 5 8 5-8 5z"} />
            </svg>
          )}
        </button>
      </div>
    );
  };

  return (
    <div className="voice-picker-layer">
      <button className="voice-picker-backdrop" aria-label={t("关闭音色选择")} onClick={onClose} />
      <section className="voice-picker-modal" role="dialog" aria-modal="true" aria-labelledby="voice-picker-title">
        <header className="voice-picker-header">
          <div>
            <span>DOUBAO SEED TTS 2.0</span>
            <h2 id="voice-picker-title">{t("选择一个喜欢的声音")}</h2>
            <p>{t("选中前可直接试听，也可以粘贴账户中的其他音色 ID")}</p>
          </div>
          <button type="button" className="icon-btn" aria-label={t("关闭音色选择")} onClick={onClose}>✕</button>
        </header>

        <div className="voice-picker-search">
          <svg viewBox="0 0 20 20" aria-hidden="true">
            <circle cx="8.5" cy="8.5" r="4.75" />
            <path d="m12 12 4 4" />
          </svg>
          <input
            value={query}
            autoFocus
            placeholder={t("搜索音色、场景，或粘贴音色 ID")}
            aria-label={t("搜索音色")}
            onChange={(event) => setQuery(event.target.value)}
          />
          <span>{filteredVoices.length}{showCustomVoice ? "+1" : ""}{t(" 个结果")}</span>
        </div>

        <div className="voice-picker-categories" aria-label={t("音色分类")}>
          {categories.map((item) => (
            <button
              type="button"
              data-active={category === item}
              key={item}
              onClick={() => setCategory(item)}
            >
              {item}
            </button>
          ))}
        </div>

        <div className="voice-picker-list">
          {showCustomVoice && renderVoice({
            value: customVoice,
            label: t("自定义音色 ID"),
            description: customVoice,
          })}
          {filteredVoices.map(renderVoice)}
          {!filteredVoices.length && !showCustomVoice && (
            <div className="voice-picker-empty">
              <strong>{t("没有匹配的音色")}</strong>
              <span>{t("可尝试其他名称，或粘贴完整的豆包音色 ID")}</span>
            </div>
          )}
        </div>

        <footer className="voice-picker-footer">
          <div>
            <span>{t("当前准备选择")}</span>
            <strong>{draftLabel}</strong>
            {previewNotice && <small role="status">{previewNotice}</small>}
          </div>
          <button
            type="button"
            className="voice-picker-confirm"
            onClick={() => {
              stopPreview();
              onConfirm(draftVoice);
              onClose();
            }}
          >
            {t("应用此音色")}</button>
        </footer>
      </section>
    </div>
  );
}

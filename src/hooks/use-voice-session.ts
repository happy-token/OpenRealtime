"use client";

// React binding for the browser Voice Session runtime.

import { setPlaybackActive } from "@/voice/audio/playback-activity";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  shouldResetTranscriptForSession,
  mergeAssistantTranscript,
  settleAssistantTranscript,
  updateAssistantOutputText,
  browserSpeechTextForResponse,
  mergeUserTranscript,
  updateAssistantCaption,
  type TranscriptEntry,
  type AssistantOutputText,
  type AssistantCaptionState,
} from "@/voice/session/transcript";
export { shouldResetTranscriptForSession, mergeAssistantTranscript, settleAssistantTranscript, updateAssistantOutputText, browserSpeechTextForResponse, mergeUserTranscript, updateAssistantCaption } from "@/voice/session/transcript";
export type { TranscriptEntry, AssistantMessageStatus, AssistantOutputText, UserTranscriptUpdate, AssistantCaptionState, AssistantCaptionUpdate } from "@/voice/session/transcript";
import type { AvatarPersonaConfigFrame, ServerToClientFrame, ToolConfigFrame, TtsConfigFrame } from "@/lib/frames";
import { BrowserAudioInput } from "@/voice/audio/browser-input";
import { BrowserAudioOutput } from "@/voice/audio/browser-output";
import type { AvatarAudioChunk, AvatarAudioSink } from "@/voice/audio/avatar-output";
import { DeviceAudioInputRuntime } from "@/voice/audio/input-runtime";
import { DeviceAudioOutputRuntime } from "@/voice/audio/output-runtime";
import { readConversationPreferences } from "@/lib/conversation-preferences";
import {
  type SessionAckV2,
} from "@/voice/protocol/v2";
import { ClientVoiceSessionController } from "@/voice/session/controller";
import {
  BrowserVoiceSessionTransport,
  connectionStateForAttempt,
  type VoiceSessionConnectionState,
} from "@/voice/session/transport";

// No-audio demo mode (SilentTtsEngine) never fires an 'ended' event.
const SPEAKING_FALLBACK_MS = 1200;
const PLAYBACK_INACTIVITY_GRACE_MS = 400;
const THINKING_FALLBACK_MS = 8000;
const HIDDEN_CAPTURE_TIMEOUT_MS = 30_000;
export const DEFAULT_ALLOW_BARGE_IN = true;

export function ttsConfigPayload(
  provider: TtsConfigFrame["provider"],
  voice: string,
  speechRate: number,
  dialect: TtsConfigFrame["dialect"],
): TtsConfigFrame {
  return {
    type: "tts_config",
    provider,
    voice,
    speech_rate: speechRate,
    dialect,
  };
}

export function avatarPersonaConfigPayload(
  avatarId: string | null,
  personaId: string | null = null,
): AvatarPersonaConfigFrame {
  return {
    type: "avatar_persona_config",
    avatar_id: avatarId,
    persona_id: personaId,
  };
}

export function toolConfigPayload(toolNames: string[], roleId?: string | null): ToolConfigFrame {
  return {
    type: "tool_config",
    tool_names: [...new Set(toolNames)],
    ...(roleId ? { role_id: roleId } : {}),
  };
}

export type ConversationState = "idle" | "listening" | "thinking" | "speaking";
export type ConnectionState = VoiceSessionConnectionState;
export { connectionStateForAttempt };

export interface PendingConfirmationView {
  confirmationId: string;
  actionDigest: string;
  summary: string;
  requiredChannel: "voice" | "strong";
  expiresAt: string;
  generation: number;
}

export function confirmationDecisionPayload(
  pending: PendingConfirmationView,
  approved: boolean,
) {
  return {
    type: "confirmation_decision" as const,
    confirmation_id: pending.confirmationId,
    action_digest: pending.actionDigest,
    approved,
  };
}

function assertNever(value: never): never {
  throw new Error(`Unhandled OpenRealtime frame: ${JSON.stringify(value)}`);
}

interface BrowserSpeechRecognitionAlternative {
  transcript: string;
}

interface BrowserSpeechRecognitionResult {
  readonly isFinal: boolean;
  readonly [index: number]: BrowserSpeechRecognitionAlternative;
}

interface BrowserSpeechRecognitionEvent {
  readonly resultIndex: number;
  readonly results: ArrayLike<BrowserSpeechRecognitionResult>;
}

interface BrowserSpeechRecognitionErrorEvent {
  readonly error: string;
}

interface BrowserSpeechRecognition {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: BrowserSpeechRecognitionEvent) => void) | null;
  onerror: ((event: BrowserSpeechRecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
}

type BrowserSpeechRecognitionConstructor = new () => BrowserSpeechRecognition;

declare global {
  interface Window {
    SpeechRecognition?: BrowserSpeechRecognitionConstructor;
    webkitSpeechRecognition?: BrowserSpeechRecognitionConstructor;
  }
}

// Cancellation takes effect at a chunk boundary, so one more audio chunk for the
// interrupted generation can already be in flight behind the cancel frame — and
// since ADR-0036 the server's frame loop and its turn task can both write to the
// socket, so their relative order isn't guaranteed either. Playing that straggler
// would put the interrupted assistant's tail after the barge-in.
// Extracted as a pure function so it is unit-testable; the rest of this hook's
// playback path needs an AudioContext and isn't.
export function shouldDropAudioFrame(
  generation: number | undefined,
  cancelledGeneration: number | null,
): boolean {
  return cancelledGeneration !== null && generation === cancelledGeneration;
}

export type PlaybackProgressPhase = "started" | "stopped" | "finished";

export function playbackProgressPayload(
  generation: number,
  phase: PlaybackProgressPhase,
  playedAudioEndUs?: number,
) {
  return {
    type: "playback_progress" as const,
    generation,
    finished: phase === "finished",
    started: phase === "started",
    stopped: phase === "stopped",
    ...(playedAudioEndUs === undefined
      ? {}
      : { played_audio_end_us: playedAudioEndUs }),
  };
}

export function playedAudioEndUs(
  startedAtSeconds: number,
  currentTimeSeconds: number,
  scheduledEndSeconds: number,
): number {
  const playedSeconds = Math.max(
    0,
    Math.min(currentTimeSeconds, scheduledEndSeconds) - startedAtSeconds,
  );
  return Math.round(playedSeconds * 1_000_000);
}

export type SpeechInputMode = "server" | "browser" | "unavailable";

export interface BrowserSpeechRecognitionErrorPolicy {
  fatal: boolean;
  message: string;
}

export function browserSpeechRecognitionErrorPolicy(
  error: string,
): BrowserSpeechRecognitionErrorPolicy {
  if (error === "not-allowed" || error === "service-not-allowed") {
    return {
      fatal: true,
      message: "当前浏览器拒绝语音识别；请启用服务端 ASR，或改用文字输入",
    };
  }
  if (error === "audio-capture") {
    return {
      fatal: true,
      message: "浏览器无法访问麦克风；请检查站点和系统麦克风权限",
    };
  }
  if (error === "aborted" || error === "no-speech") {
    return { fatal: false, message: "" };
  }
  return {
    fatal: true,
    message: `浏览器语音识别不可用：${error}；请启用服务端 ASR，或改用文字输入`,
  };
}

export function speechInputMode(
  serverAsr: boolean,
  browserSpeechRecognition: boolean,
): SpeechInputMode {
  if (serverAsr) return "server";
  return browserSpeechRecognition ? "browser" : "unavailable";
}

export function shouldArmTextOnlySpeechFallback(serverTts: boolean | null): boolean {
  return serverTts === false;
}

export function shouldOptimisticallyAppendUserTranscript(
  userTranscriptStreaming: boolean | null,
): boolean {
  return userTranscriptStreaming !== true;
}

export function responseCompletionFallbackDelayMs(
  serverTts: boolean | null,
  speakingGeneration: number | null,
  responseGeneration: number,
  scheduledSourceCount: number,
  scheduledAudioRemainingMs: number,
): number | null {
  void scheduledSourceCount;
  if (
    serverTts === false
    || speakingGeneration !== responseGeneration
  ) {
    return null;
  }
  const remainingMs = Number.isFinite(scheduledAudioRemainingMs)
    ? Math.max(0, scheduledAudioRemainingMs)
    : 0;
  return Math.ceil(remainingMs) + SPEAKING_FALLBACK_MS;
}

export function playbackInactivityFallbackDelayMs(
  scheduledAudioRemainingMs: number,
): number {
  const remainingMs = Number.isFinite(scheduledAudioRemainingMs)
    ? Math.max(0, scheduledAudioRemainingMs)
    : 0;
  return Math.ceil(remainingMs) + PLAYBACK_INACTIVITY_GRACE_MS;
}

export interface EndedAudioSource {
  addEventListener(type: "ended", listener: () => void): void;
  start(when: number): void;
}

export function startAudioSource(
  source: EndedAudioSource,
  startAt: number,
  onEnded: () => void,
): void {
  source.addEventListener("ended", onEnded);
  source.start(startAt);
}

function browserSpeechRecognitionConstructor(): BrowserSpeechRecognitionConstructor | null {
  if (typeof window === "undefined") return null;
  return window.SpeechRecognition ?? window.webkitSpeechRecognition ?? null;
}

export interface VoiceSessionViewModel {
  state: ConversationState;
  level: number;
  caption: string;
  transcript: TranscriptEntry[];
  connection: ConnectionState;
  sessionId: string | null;
  micActive: boolean;
  micAvailable: boolean;
  ttsConfigurable: boolean;
  ttsPreviewAvailable: boolean;
  ttsConfigStatus: string;
  sessionError: string | null;
  credentialSummary: string | null;
  trialSecondsRemaining: number | null;
  prepareAdmission: (admission: {
    ticket: string;
    deadline?: string | null;
    sources?: {
      asr: { source: "platform" | "personal" };
      tts: { source: "platform" | "personal" };
      llm: { source: "platform" | "personal" };
      anam?: { source: "platform" | "personal" };
    };
  } | null) => void;
  pendingConfirmation: PendingConfirmationView | null;
  start: (provider?: TtsConfigFrame["provider"]) => Promise<void>;
  unlockAudioOutput: () => Promise<void>;
  retryConnection: () => void;
  stop: () => void;
  terminate: () => void;
  clearConversationDisplay: () => void;
  sendText: (text: string) => boolean;
  stopReply: () => boolean;
  setNoiseSuppression: (enabled: boolean) => void;
  setBargeInMuted: (muted: boolean) => void;
  setVolume: (volume: number) => void;
  configureTts: (
    provider: TtsConfigFrame["provider"],
    voice: string,
    speechRate: number,
    dialect: TtsConfigFrame["dialect"],
  ) => void;
  configureAvatarPersona: (avatarId: string | null, personaId?: string | null) => void;
  configureTools: (toolNames: string[], roleId?: string | null) => void;
  setAvatarAudioSink: (sink: AvatarAudioSink | null) => void;
  resolveConfirmation: (approved: boolean) => void;
}

export function useVoiceSession({ publicVoiceEnabled = false, roleProviders }: { publicVoiceEnabled?: boolean; roleProviders?: { asr?: "doubao" | "dashscope" | null; llm?: "deepseek" | "openai" | null } } = {}): VoiceSessionViewModel {
  const [state, setStateValue] = useState<ConversationState>("idle");
  const [level, setLevel] = useState(0);
  const [caption, setCaption] = useState("");
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [micActive, setMicActiveValue] = useState(false);
  const [micAvailable, setMicAvailable] = useState(false);
  const [ttsConfigurable, setTtsConfigurable] = useState(false);
  const [ttsPreviewAvailable, setTtsPreviewAvailable] = useState(false);
  const [ttsConfigStatus, setTtsConfigStatus] = useState("");
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [credentialSummary, setCredentialSummary] = useState<string | null>(null);
  const [trialSecondsRemaining, setTrialSecondsRemaining] = useState<number | null>(null);
  const [pendingConfirmation, setPendingConfirmation] = useState<PendingConfirmationView | null>(null);

  const transportRef = useRef<BrowserVoiceSessionTransport | null>(null);
  const preparedAdmissionRef = useRef<{
    ticket: string;
    deadline?: string | null;
    sources?: {
      asr: { source: "platform" | "personal" };
      tts: { source: "platform" | "personal" };
      llm: { source: "platform" | "personal" };
      anam?: { source: "platform" | "personal" };
    };
  } | null>(null);
  const pendingPublicConnectionRef = useRef<Promise<void> | null>(null);
  const trialDeadlineRef = useRef<number | null>(null);
  const publicCapabilitiesReadyRef = useRef<(() => void) | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const pendingTtsConfigRef = useRef<{
    provider: TtsConfigFrame["provider"];
    voice: string;
    speechRate: number;
    dialect: TtsConfigFrame["dialect"];
  } | null>(null);
  const pendingAvatarPersonaRef = useRef<{
    avatarId: string | null;
    personaId: string | null;
  } | undefined>(undefined);
  const pendingToolNamesRef = useRef<{ names: string[]; roleId: string | null } | undefined>(undefined);
  const pendingConfirmationRef = useRef<PendingConfirmationView | null>(null);
  const avatarAudioSinkRef = useRef<AvatarAudioSink | null>(null);
  const outputVolumeRef = useRef(0.8);

  const micActiveRef = useRef(false);
  const sessionOutputEnabledRef = useRef(false);
  const inputRuntimeRef = useRef(new DeviceAudioInputRuntime());
  const outputRuntimeRef = useRef(new DeviceAudioOutputRuntime());
  const voiceControllerRef = useRef(
    new ClientVoiceSessionController({
      input: inputRuntimeRef.current,
      output: outputRuntimeRef.current,
      providers: roleProviders,
    }),
  );
  const browserRecognitionRef = useRef<BrowserSpeechRecognition | null>(null);
  const noiseSuppressionRef = useRef(true);
  const bargeInMutedRef = useRef(!DEFAULT_ALLOW_BARGE_IN);

  const cancelledGenerationRef = useRef<number | null>(null);

  const stateRef = useRef<ConversationState>("idle");
  const speakingGenerationRef = useRef<number | null>(null);
  const fallbackTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const playbackInactivityTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const thinkingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const rafRef = useRef<number | null>(null);
  const serverAsrRef = useRef<boolean | null>(null);
  const serverTtsRef = useRef<boolean | null>(null);
  const userTranscriptStreamingRef = useRef<boolean | null>(null);
  const assistantOutputTextRef = useRef<AssistantOutputText>({
    generation: null,
    display: "",
    spoken: "",
  });
  const assistantCaptionRef = useRef<AssistantCaptionState>({
    text: "",
    spokenGeneration: null,
  });

  // Imperative public API: assigned inside the mount effect below (each
  // function closes over that connection's state), invoked via the stable
  // callbacks returned at the bottom of this hook.
  const startRef = useRef<(provider?: TtsConfigFrame["provider"]) => Promise<void>>(async () => {});
  const unlockAudioOutputRef = useRef<() => Promise<void>>(async () => {});
  const retryConnectionRef = useRef<() => void>(() => {});
  const stopRef = useRef<() => void>(() => {});
  const terminateRef = useRef<() => void>(() => {});
  const sendTextRef = useRef<(text: string) => boolean>(() => false);
  const stopReplyRef = useRef<() => boolean>(() => false);
  const setNoiseSuppressionRef = useRef<(enabled: boolean) => void>(() => {});
  const setBargeInMutedRef = useRef<(muted: boolean) => void>(() => {});
  const setVolumeRef = useRef<(volume: number) => void>(() => {});
  const configureTtsRef = useRef<(
    provider: TtsConfigFrame["provider"],
    voice: string,
    speechRate: number,
    dialect: TtsConfigFrame["dialect"],
  ) => void>(() => {});
  const configureAvatarPersonaRef = useRef<(
    avatarId: string | null,
    personaId?: string | null,
  ) => void>(() => {});
  const configureToolsRef = useRef<(toolNames: string[], roleId?: string | null) => void>(() => {});
  const resolveConfirmationRef = useRef<(approved: boolean) => void>(() => {});

  const setState = useCallback((next: ConversationState) => {
    if (next === stateRef.current) return;
    const prev = stateRef.current;
    stateRef.current = next;
    if (next === "listening" && prev !== "listening") setCaption("");
    setStateValue(next);
  }, []);

  const setMicActive = useCallback((active: boolean) => {
    micActiveRef.current = active;
    setMicActiveValue(active);
  }, []);

  useEffect(() => {
    if (!publicVoiceEnabled) return;
    const timer = window.setInterval(() => {
      setTrialSecondsRemaining(trialDeadlineRef.current === null
        ? null : Math.max(0, Math.ceil((trialDeadlineRef.current - Date.now()) / 1000)));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [publicVoiceEnabled]);

  useEffect(() => {
    let hiddenCaptureTimer: ReturnType<typeof setTimeout> | null = null;
    const outputGraph = new BrowserAudioOutput({
      runtime: outputRuntimeRef.current,
      onStarted: (generation) => reportPlaybackProgress(generation, "started"),
      onResumed: (generation) => {
        if (speakingGenerationRef.current === generation) setPlaybackActive(true);
      },
    });
    unlockAudioOutputRef.current = () => outputGraph.unlock();
    const inputGraph = new BrowserAudioInput({
      runtime: inputRuntimeRef.current,
      controller: voiceControllerRef.current,
      isTransportOpen: () => transportRef.current?.isOpen ?? false,
      send: (frame) => transportRef.current?.send(frame) ?? false,
      getNoiseSuppression: () => noiseSuppressionRef.current,
      shouldDropFrame: () => (
        bargeInMutedRef.current && stateRef.current === "speaking"
      ),
      onFailure: setCaption,
      onCaptureStopped: () => {
        setMicActive(false);
        if (stateRef.current === "listening") setState("idle");
      },
    });

    function enterSpeaking(generation: number) {
      speakingGenerationRef.current = generation;
      setState("speaking");
    }

    function leaveSpeaking() {
      setPlaybackActive(false);
      speakingGenerationRef.current = null;
      setState(micActiveRef.current ? "listening" : "idle");
    }

    function armFallback(generation: number, delayMs = SPEAKING_FALLBACK_MS) {
      if (fallbackTimerRef.current) clearTimeout(fallbackTimerRef.current);
      fallbackTimerRef.current = setTimeout(() => {
        if (speakingGenerationRef.current === generation) leaveSpeaking();
      }, delayMs);
    }

    function clearThinkingFallback() {
      if (!thinkingTimerRef.current) return;
      clearTimeout(thinkingTimerRef.current);
      thinkingTimerRef.current = null;
    }

    function armThinkingFallback() {
      clearThinkingFallback();
      thinkingTimerRef.current = setTimeout(() => {
        thinkingTimerRef.current = null;
        if (stateRef.current !== "thinking") return;
        setCaption("响应超时，请再说一次");
        setState(micActiveRef.current ? "listening" : "idle");
      }, THINKING_FALLBACK_MS);
    }

    function clearPlaybackInactivityFallback() {
      if (!playbackInactivityTimerRef.current) return;
      clearTimeout(playbackInactivityTimerRef.current);
      playbackInactivityTimerRef.current = null;
    }

    function armPlaybackInactivityFallback(generation: number) {
      clearPlaybackInactivityFallback();
      const remainingMs = outputGraph.remainingScheduledMs;
      playbackInactivityTimerRef.current = setTimeout(() => {
        playbackInactivityTimerRef.current = null;
        if (
          speakingGenerationRef.current !== generation
          || outputGraph.scheduledSourceCount > 0
        ) return;
        // The response may still be waiting on a slow tool. This only releases
        // the visual/audio floor; a later chunk re-enters SPEAK naturally.
        leaveSpeaking();
      }, playbackInactivityFallbackDelayMs(remainingMs));
    }

    function replayAvatarAudio(chunk: AvatarAudioChunk, isFinal: boolean) {
      if (!sessionOutputEnabledRef.current
        || shouldDropAudioFrame(chunk.generation, cancelledGenerationRef.current)
        || speakingGenerationRef.current !== chunk.generation) return;
      outputGraph.play({
        ...chunk,
        isFinal,
        onEnded: () => {
          if (speakingGenerationRef.current !== chunk.generation) return;
          if (isFinal) {
            clearPlaybackInactivityFallback();
            leaveSpeaking();
            reportPlaybackFinished(chunk.generation);
          } else {
            armPlaybackInactivityFallback(chunk.generation);
          }
        },
      });
    }

    function handleFrame(frame: ServerToClientFrame) {
      if (frame.type.startsWith("assistant_") && !sessionOutputEnabledRef.current) {
        return;
      }
      switch (frame.type) {
        case "session_ack":
          if (
            shouldResetTranscriptForSession(
              sessionIdRef.current,
              frame.session_id ?? null,
              frame.previous_voice_session_id ?? null,
            )
          ) {
            setTranscript([]);
            setCaption("");
            assistantOutputTextRef.current = { generation: null, display: "", spoken: "" };
            assistantCaptionRef.current = { text: "", spokenGeneration: null };
            pendingConfirmationRef.current = null;
            setPendingConfirmation(null);
          }
          sessionIdRef.current = frame.session_id ?? null;
          setSessionId(sessionIdRef.current);
          outputGraph.beginEpoch(crypto.randomUUID());
          if (
            frame.protocol_version === 2
            && typeof frame.resume_token === "string"
          ) {
            voiceControllerRef.current.acceptSession(frame as SessionAckV2);
            if (micActiveRef.current && inputGraph.isActive) {
              if (transportRef.current?.isOpen) {
                inputGraph.beginEpoch();
              }
            }
          }
          break;
        case "input_audio_ack":
          try {
            inputGraph.acknowledge(frame);
          } catch {
            inputGraph.resetForDisconnect();
            setCaption("服务器音频确认无效，请重新说一次");
          }
          break;
        case "audio_gap":
          inputGraph.failGap(frame.input_epoch);
          break;
        case "voice_session_ready":
          setSessionError(null);
          voiceControllerRef.current.applyEvent(frame);
          inputGraph.release(frame.input_epoch);
          reportRecoveredConnection();
          break;
        case "voice_session_phase_changed":
          voiceControllerRef.current.applyEvent(frame);
          break;
        case "voice_session_snapshot":
          voiceControllerRef.current.applySnapshot(frame);
          break;
        case "voice_session_event_tail":
          voiceControllerRef.current.applyEventTail(frame);
          break;
        case "voice_session_failed":
          setSessionError(frame.safe_message);
          setCaption(frame.safe_message);
          if (frame.session_disposition === "continuation_required") {
            voiceControllerRef.current.beginContinuation();
            transportRef.current?.reconnect();
          }
          if (frame.session_disposition === "close") {
            if (publicVoiceEnabled) {
              sessionOutputEnabledRef.current = false;
              trialDeadlineRef.current = null;
              setTrialSecondsRemaining(null);
              stopMic();
              setMicActive(false);
              setState("idle");
            }
            setConnection("error");
          }
          break;
        case "session_capabilities": {
          serverAsrRef.current = frame.server_asr ?? false;
          serverTtsRef.current = frame.server_tts ?? false;
          userTranscriptStreamingRef.current = frame.user_transcript_streaming ?? false;
          setTtsConfigurable(frame.tts_configurable ?? false);
          setTtsPreviewAvailable(frame.tts_preview ?? false);
          // The endpoint may still be opening when the socket first accepts
          // frames. Apply the selected voice once its capabilities arrive.
          const selectedTts = pendingTtsConfigRef.current;
          if (selectedTts && frame.tts_configurable) {
            transportRef.current?.send(ttsConfigPayload(
              selectedTts.provider,
              selectedTts.voice,
              selectedTts.speechRate,
              selectedTts.dialect,
            ));
          }
          const browserAsr = browserSpeechRecognitionConstructor() !== null;
          setMicAvailable(serverAsrRef.current || (!publicVoiceEnabled && browserAsr));
          if (publicVoiceEnabled && !serverAsrRef.current) {
            setCaption("服务端语音识别不可用，请检查 Key 或稍后重试");
          } else if (!serverAsrRef.current && browserAsr) {
            setCaption("服务端 ASR 未配置，已切换到浏览器实时语音识别");
          } else if (!serverAsrRef.current) {
            setCaption("语音识别不可用，请先使用文字输入");
          }
          publicCapabilitiesReadyRef.current?.();
          publicCapabilitiesReadyRef.current = null;
          break;
        }
        case "tts_config_ack":
          setTtsConfigStatus(frame.applied ? "" : frame.error ?? "语音配置应用失败");
          break;
        case "confirmation_requested":
          pendingConfirmationRef.current = {
            confirmationId: frame.confirmation_id,
            actionDigest: frame.action_digest,
            summary: frame.summary,
            requiredChannel: frame.required_channel,
            expiresAt: frame.expires_at,
            generation: frame.generation,
          };
          setPendingConfirmation(pendingConfirmationRef.current);
          setCaption(`需要确认：${frame.summary}`);
          break;
        case "confirmation_resolution":
          if (pendingConfirmationRef.current?.confirmationId === frame.confirmation_id) {
            pendingConfirmationRef.current = null;
          }
          setPendingConfirmation((current) => (
            current?.confirmationId === frame.confirmation_id ? null : current
          ));
          setCaption(frame.message);
          break;
        case "user_transcript":
          setCaption(`你：${frame.text}`);
          if (typeof frame.generation === "number") {
            setTranscript((prev) =>
              mergeUserTranscript(
                prev,
                frame.generation as number,
                frame.text ?? "",
                {
                  turnId: frame.turn_id,
                  revision: frame.transcript_revision,
                  isFinal: frame.is_final,
                },
              ),
            );
          } else if (frame.is_final !== false) {
            setTranscript((prev) => [...prev, { role: "user", text: frame.text ?? "" }]);
          }
          if (frame.is_final !== false) {
            setState("thinking");
            armThinkingFallback();
          }
          break;
        case "assistant_text":
          clearThinkingFallback();
          if (speakingGenerationRef.current !== frame.generation) {
            enterSpeaking(frame.generation as number);
          }
          assistantOutputTextRef.current = updateAssistantOutputText(
            assistantOutputTextRef.current,
            "display",
            frame.generation as number,
            frame.text ?? "",
          );
          assistantCaptionRef.current = updateAssistantCaption(
            assistantCaptionRef.current,
            {
              kind: "display",
              generation: frame.generation as number,
              text: frame.text ?? "",
            },
          );
          setCaption(assistantCaptionRef.current.text);
          setTranscript((prev) =>
            mergeAssistantTranscript(
              prev,
              frame.generation as number,
              frame.text ?? "",
            ),
          );
          if (shouldArmTextOnlySpeechFallback(serverTtsRef.current)) {
            armFallback(frame.generation as number);
          }
          break;
        case "assistant_speech_text":
          clearThinkingFallback();
          if (speakingGenerationRef.current !== frame.generation) {
            enterSpeaking(frame.generation as number);
          }
          assistantOutputTextRef.current = updateAssistantOutputText(
            assistantOutputTextRef.current,
            "spoken",
            frame.generation as number,
            frame.text ?? "",
          );
          assistantCaptionRef.current = updateAssistantCaption(
            assistantCaptionRef.current,
            {
              kind: "spoken",
              generation: frame.generation as number,
              text: frame.text ?? "",
            },
          );
          setCaption(assistantCaptionRef.current.text);
          break;
        case "assistant_audio": {
          clearThinkingFallback();
          clearPlaybackInactivityFallback();
          if (shouldDropAudioFrame(frame.generation, cancelledGenerationRef.current)) break;
          if (fallbackTimerRef.current) clearTimeout(fallbackTimerRef.current);
          if (speakingGenerationRef.current !== frame.generation) {
            enterSpeaking(frame.generation as number);
          }
          const audioChunk: AvatarAudioChunk = {
            pcm16Base64: frame.pcm16_base64 as string,
            sampleRateHz: frame.sample_rate_hz as number,
            generation: frame.generation as number,
            speechId: `response:${frame.generation}`,
            sequence: 0,
            isFinal: true,
            onFallback: (isFinal) => replayAvatarAudio(audioChunk, isFinal),
            onStarted: () => reportPlaybackProgress(frame.generation as number, "started"),
            onEnded: () => {
              if (speakingGenerationRef.current !== frame.generation) return;
              leaveSpeaking();
              reportPlaybackFinished(frame.generation as number);
            },
          };
          const avatarSink = avatarAudioSinkRef.current;
          const renderedByAvatar = avatarSink?.enqueue(audioChunk) ?? false;
          if (renderedByAvatar) avatarSink?.completeGeneration(frame.generation as number);
          else {
            outputGraph.play(audioChunk);
            reportPlaybackQuality(frame.generation as number);
          }
          break;
        }
        case "assistant_audio_chunk": {
          clearThinkingFallback();
          clearPlaybackInactivityFallback();
          if (shouldDropAudioFrame(frame.generation, cancelledGenerationRef.current)) break;
          if (serverTtsRef.current === false && !frame.pcm16_base64) break;
          if (fallbackTimerRef.current) clearTimeout(fallbackTimerRef.current);
          if (speakingGenerationRef.current !== frame.generation) {
            enterSpeaking(frame.generation as number);
          }
          const audioChunk: AvatarAudioChunk = {
            pcm16Base64: frame.pcm16_base64 as string,
            sampleRateHz: frame.sample_rate_hz as number,
            generation: frame.generation as number,
            speechId: frame.speech_id ?? `response:${frame.generation}`,
            sequence: frame.sequence as number,
            isFinal: frame.is_final as boolean,
            onFallback: (isFinal) => replayAvatarAudio(audioChunk, isFinal),
            onStarted: () => {
              if (speakingGenerationRef.current !== frame.generation) {
                enterSpeaking(frame.generation as number);
              }
              reportPlaybackProgress(frame.generation as number, "started");
            },
            onEnded: () => {
              if (frame.is_final) {
                clearPlaybackInactivityFallback();
                  if (speakingGenerationRef.current !== frame.generation) return;
                  leaveSpeaking();
                  reportPlaybackFinished(frame.generation as number);
                return;
              }
              armPlaybackInactivityFallback(frame.generation as number);
            },
          };
          const renderedByAvatar = avatarAudioSinkRef.current?.enqueue(audioChunk) ?? false;
          if (!renderedByAvatar) outputGraph.play(audioChunk);
          if (frame.is_final && !renderedByAvatar) {
            reportPlaybackQuality(frame.generation as number);
          }
          break;
        }
        case "assistant_response_completed": {
          clearThinkingFallback();
          setTranscript((previous) => settleAssistantTranscript(
            previous,
            frame.generation as number,
            "completed",
          ));
          const avatarSink = avatarAudioSinkRef.current;
          const avatarPlaybackStarted = avatarSink?.completeGeneration(
            frame.generation as number,
          ) ?? false;
          const browserSpeechText = browserSpeechTextForResponse(
            assistantOutputTextRef.current,
            frame.generation as number,
          );
          if (!publicVoiceEnabled && serverTtsRef.current === false && browserSpeechText) {
            speakWithBrowser(
              browserSpeechText,
              frame.generation as number,
            );
          } else if (!avatarPlaybackStarted && !avatarSink?.isActive(frame.generation as number)) {
            // A configured server TTS can still fail before yielding its first
            // audio chunk. Do not report idle during normal provider startup;
            // arm the safety timer only after the response has completed.
            const remainingMs = outputGraph.remainingScheduledMs;
            const fallbackDelayMs = responseCompletionFallbackDelayMs(
              serverTtsRef.current,
              speakingGenerationRef.current,
              frame.generation as number,
              outputGraph.scheduledSourceCount,
              remainingMs,
            );
            if (fallbackDelayMs !== null) {
              armFallback(frame.generation as number, fallbackDelayMs);
            }
          }
          break;
        }
        case "assistant_speech_cancelled": {
          clearThinkingFallback();
          clearPlaybackInactivityFallback();
          // The server confirmed a barge-in (τ9). Nothing new will arrive for
          // this generation, so playChunk's own generation-change reset will
          // never run — this is the only thing that stops audio already
          // scheduled in the Web Audio graph.
          cancelledGenerationRef.current = frame.generation ?? null;
          setTranscript((previous) => settleAssistantTranscript(
            previous,
            frame.generation as number,
            frame.reason === "failed" ? "failed" : "interrupted",
          ));
          reportPlaybackQuality(frame.generation as number);
          const v2Progress = outputGraph.cancelGeneration(frame.generation as number);
          avatarAudioSinkRef.current?.cancelGeneration(frame.generation as number);
          if (v2Progress) transportRef.current?.send(v2Progress);
          if (fallbackTimerRef.current) clearTimeout(fallbackTimerRef.current);
          if (!v2Progress) {
            reportPlaybackProgress(frame.generation as number, "stopped");
          }
          // Synchronous, so speakingGenerationRef is null before the `ended`
          // events that stop() is about to schedule fire — which is what keeps
          // them from reporting a playback completion that never happened.
          leaveSpeaking();
          break;
        }
        default:
          assertNever(frame);
      }
    }

    function reportPlaybackProgress(
      generation: number,
      phase: PlaybackProgressPhase,
    ) {
      setPlaybackActive(phase === "started");
      // Client-observed playback anchors. They are only emitted by genuine
      // start/end events or an explicit server cancellation, never by the
      // fallback timer used for no-audio demo paths.
      const transport = transportRef.current;
      if (!transport?.isOpen) return;
      const v2Progress = outputGraph.playbackProgress(generation, phase);
      transport.send(
        v2Progress ?? playbackProgressPayload(generation, phase),
      );
    }

    function reportRecoveredConnection() {
      transportRef.current?.reportRecovered();
    }

    function reportPlaybackFinished(generation: number) {
      setPlaybackActive(false);
      const transport = transportRef.current;
      if (!transport?.isOpen) return;
      transport.send(
        outputGraph.finishGeneration(generation)
          ?? playbackProgressPayload(generation, "finished"),
      );
    }

    function reportPlaybackQuality(generation: number) {
      const transport = transportRef.current;
      if (!transport?.isOpen) return;
      const quality = outputGraph.takeQuality(generation);
      if (!quality) return;
      transport.send(quality);
    }

    function speakWithBrowser(text: string, generation: number) {
      if (!("speechSynthesis" in window) || !("SpeechSynthesisUtterance" in window)) {
        leaveSpeaking();
        return;
      }
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = "zh-CN";
      enterSpeaking(generation);
      utterance.addEventListener("start", () => {
        reportPlaybackProgress(generation, "started");
      });
      utterance.addEventListener("end", () => {
        if (speakingGenerationRef.current !== generation) return;
        leaveSpeaking();
        reportPlaybackFinished(generation);
      });
      utterance.addEventListener("error", () => {
        if (speakingGenerationRef.current === generation) leaveSpeaking();
      });
      window.speechSynthesis.speak(utterance);
    }

    function startBrowserSpeechRecognition() {
      const Recognition = browserSpeechRecognitionConstructor();
      if (!Recognition) throw new Error("当前浏览器不支持语音识别，请使用文字输入");
      const recognition = new Recognition();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = "zh-CN";
      recognition.onresult = (event) => {
        let interimText = "";
        let finalText = "";
        for (let index = event.resultIndex; index < event.results.length; index += 1) {
          const result = event.results[index];
          const text = result[0]?.transcript ?? "";
          if (result.isFinal) finalText += text;
          else interimText += text;
        }
        if (interimText.trim()) {
          setCaption(`你：${interimText.trim()}`);
          setState("listening");
        }
        if (finalText.trim()) submitUserText(finalText.trim());
      };
      recognition.onerror = (event) => {
        const policy = browserSpeechRecognitionErrorPolicy(event.error);
        if (!policy.message) return;
        setCaption(policy.message);
        if (!policy.fatal) return;
        recognition.onend = null;
        if (browserRecognitionRef.current === recognition) {
          browserRecognitionRef.current = null;
        }
        setMicAvailable(false);
        setMicActive(false);
        setState("idle");
      };
      recognition.onend = () => {
        if (!micActiveRef.current || browserRecognitionRef.current !== recognition) return;
        try {
          recognition.start();
        } catch {
          setMicActive(false);
          setState("idle");
        }
      };
      browserRecognitionRef.current = recognition;
      recognition.start();
    }

    function stopMic() {
      if (browserRecognitionRef.current) {
        const recognition = browserRecognitionRef.current;
        browserRecognitionRef.current = null;
        recognition.onend = null;
        recognition.stop();
      }
      inputGraph.stop();
    }

    // ---------- level metering ----------

    function tickLevel() {
      let currentLevel = 0;
      if (stateRef.current === "listening") {
        currentLevel = inputGraph.readLevel();
      } else if (
        stateRef.current === "speaking"
      ) {
        currentLevel = outputGraph.readLevel();
      }
      setLevel(Math.max(0, Math.min(1, currentLevel * 2.2)));
      rafRef.current = requestAnimationFrame(tickLevel);
    }

    async function preparePublicConnection(provider: TtsConfigFrame["provider"] = "bailian") {
      if (transportRef.current?.isOpen && serverAsrRef.current !== null) return;
      if (pendingPublicConnectionRef.current) return pendingPublicConnectionRef.current;
      const attempt = (async () => {
        type PublicAdmissionResult = {
          ticket?: string;
          error?: string;
          deadline?: string | null;
          sources?: {
            asr: { provider?: string; source: "platform" | "personal"; instanceName?: string };
            tts: { provider?: string; source: "platform" | "personal"; instanceName?: string };
            llm: { provider?: string; source: "platform" | "personal"; instanceName?: string };
            anam?: { source: "platform" | "personal" };
          };
        };
        let result: PublicAdmissionResult | null = preparedAdmissionRef.current;
        preparedAdmissionRef.current = null;
        if (!result) {
          const response = await fetch("/api/voice/admission", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ttsProvider: provider === "bailian" ? "dashscope" : "doubao",
              ...(pendingToolNamesRef.current?.roleId ? { roleId: pendingToolNamesRef.current.roleId } : {}) }),
          });
          result = await response.json() as PublicAdmissionResult;
          if (!response.ok || !result?.ticket) throw new Error(result?.error || "语音服务暂时不可用");
        }
        if (!result.ticket) throw new Error("语音会话准入无效，请重新开始");
        trialDeadlineRef.current = result.deadline ? Date.parse(result.deadline) : null;
        setTrialSecondsRemaining(trialDeadlineRef.current === null
          ? null : Math.max(0, Math.ceil((trialDeadlineRef.current - Date.now()) / 1000)));
        if (result.sources) {
          const label = (source: "platform" | "personal") => source === "personal" ? "我的额度" : "平台额度";
          const configured = (entry: { provider?: string; source: "platform" | "personal"; instanceName?: string }) =>
            `${entry.instanceName || entry.provider || "默认配置"}（${label(entry.source)}）`;
          const avatar = result.sources.anam ? ` · 数字人：${label(result.sources.anam.source)}` : "";
          setCredentialSummary(`语音识别：${configured(result.sources.asr)} · 语音合成：${configured(result.sources.tts)} · 对话模型：${configured(result.sources.llm)}${avatar}`);
        }
        const configured = process.env.NEXT_PUBLIC_VOICE_WS_URL;
        const base = configured || `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/voice`;
        const url = new URL(base, location.href);
        if (url.protocol !== "ws:" && url.protocol !== "wss:") throw new Error("语音连接地址无效");
        if (location.protocol === "https:" && url.protocol !== "wss:") throw new Error("语音连接需要安全的 WSS 地址");
        url.searchParams.set("admission", result.ticket);
        voiceControllerRef.current.startNewSession();
        serverAsrRef.current = null;
        serverTtsRef.current = null;
        transportRef.current?.dispose();
        const transport = createTransport(url.href);
        transportRef.current = transport;
        await new Promise<void>((resolve, reject) => {
          const timeout = window.setTimeout(() => {
            publicCapabilitiesReadyRef.current = null;
            transport.dispose();
            if (transportRef.current === transport) transportRef.current = null;
            void fetch(`/api/voice/admission?ticket=${encodeURIComponent(result.ticket!)}`, {
              method: "DELETE", keepalive: true,
            }).catch(() => undefined);
            reject(new Error("语音连接超时，请手动重试"));
          }, 8000);
          publicCapabilitiesReadyRef.current = () => {
            window.clearTimeout(timeout);
            resolve();
          };
          transport.start();
        });
      })();
      pendingPublicConnectionRef.current = attempt;
      try { await attempt; } finally { pendingPublicConnectionRef.current = null; }
    }

    startRef.current = async (provider) => {
      if (micActiveRef.current) return;
      if (publicVoiceEnabled) await preparePublicConnection(provider);
      if (serverAsrRef.current === null) {
        throw new Error("正在等待服务端语音能力信息，请稍后重试");
      }
      if (publicVoiceEnabled && (!serverAsrRef.current || !serverTtsRef.current)) {
        throw new Error("完整语音服务暂时不可用，请检查服务商配置后手动重试");
      }
      const mode = speechInputMode(
        serverAsrRef.current,
        browserSpeechRecognitionConstructor() !== null,
      );
      try {
        outputGraph.activate();
        if (mode === "server") await inputGraph.start();
        else if (mode === "browser") startBrowserSpeechRecognition();
        else throw new Error("语音识别不可用，请先使用文字输入");
        sessionOutputEnabledRef.current = true;
        setMicActive(true);
        if (stateRef.current === "idle") setState("listening");
      } catch (error) {
        sessionOutputEnabledRef.current = false;
        throw error;
      }
    };

    retryConnectionRef.current = () => transportRef.current?.retryNow();

    stopRef.current = () => {
      stopMic();
      setMicActive(false);
      if (stateRef.current === "listening") setState("idle");
    };

    terminateRef.current = () => {
      if (publicVoiceEnabled) {
        transportRef.current?.dispose();
        transportRef.current = null;
        serverAsrRef.current = null;
        serverTtsRef.current = null;
        setConnection("connecting");
        setCredentialSummary(null);
        trialDeadlineRef.current = null;
        setTrialSecondsRemaining(null);
        preparedAdmissionRef.current = null;
      }
      sessionOutputEnabledRef.current = false;
      stopMic();
      setMicActive(false);
      if (fallbackTimerRef.current) {
        clearTimeout(fallbackTimerRef.current);
        fallbackTimerRef.current = null;
      }
      clearPlaybackInactivityFallback();
      clearThinkingFallback();
      window.speechSynthesis?.cancel();
      outputGraph.reset();
      avatarAudioSinkRef.current?.reset();
      setPlaybackActive(false);
      speakingGenerationRef.current = null;
      assistantOutputTextRef.current = { generation: null, display: "", spoken: "" };
      assistantCaptionRef.current = { text: "", spokenGeneration: null };
      setCaption("");
      setSessionError(null);
      setState("idle");
    };

    stopReplyRef.current = () => {
      const transport = transportRef.current;
      if (!transport?.isOpen || !["thinking", "speaking"].includes(stateRef.current)) return false;
      const sent = transport.send({ type: "cancel_assistant_response" });
      if (!sent) setSessionError("暂时无法停止回复，请重试。");
      return sent;
    };

    function submitUserText(text: string) {
      const transport = transportRef.current;
      if (!text.trim() || !transport?.isOpen) return false;
      try {
        if (!transport.send({ type: "user_text", text })) return false;
      } catch {
        return false;
      }
      setSessionError(null);
      outputGraph.activate();
      sessionOutputEnabledRef.current = true;
      setCaption(`你：${text}`);
      if (
        shouldOptimisticallyAppendUserTranscript(
          userTranscriptStreamingRef.current,
        )
      ) {
        setTranscript((previous) => {
          const last = previous.at(-1);
          if (
            last?.role === "user"
            && last.generation === undefined
            && last.text === text
          ) {
            return previous;
          }
          return [
            ...previous,
            { role: "user", text, isFinal: true },
          ];
        });
      }
      setPlaybackActive(false);
      speakingGenerationRef.current = null;
      setState("thinking");
      armThinkingFallback();
      return true;
    }

    sendTextRef.current = submitUserText;

    setNoiseSuppressionRef.current = (enabled: boolean) => {
      noiseSuppressionRef.current = enabled;
      if (micActiveRef.current && serverAsrRef.current) {
        stopMic();
        inputGraph.start().catch(() => {
          setMicActive(false);
          if (stateRef.current === "listening") setState("idle");
        });
      }
    };

    setBargeInMutedRef.current = (muted: boolean) => {
      bargeInMutedRef.current = muted;
    };

    setVolumeRef.current = (volume: number) => {
      outputVolumeRef.current = volume;
      outputGraph.setVolume(volume);
      avatarAudioSinkRef.current?.setVolume(volume);
    };
    const preferences = readConversationPreferences();
    setVolumeRef.current(preferences.volume / 100);
    noiseSuppressionRef.current = preferences.noiseSuppression;
    bargeInMutedRef.current = !preferences.allowBargeIn;

    configureTtsRef.current = (provider, voice, speechRate, dialect) => {
      pendingTtsConfigRef.current = { provider, voice, speechRate, dialect };
      const transport = transportRef.current;
      if (!transport?.isOpen) {
        setTtsConfigStatus("");
        return;
      }
      setTtsConfigStatus("");
      transport.send(ttsConfigPayload(provider, voice, speechRate, dialect));
    };
    configureAvatarPersonaRef.current = (avatarId, personaId = null) => {
      pendingAvatarPersonaRef.current = { avatarId, personaId };
      const transport = transportRef.current;
      if (!transport?.isOpen) return;
      transport.send(avatarPersonaConfigPayload(avatarId, personaId));
    };
    configureToolsRef.current = (toolNames, roleId = null) => {
      pendingToolNamesRef.current = { names: [...new Set(toolNames)], roleId };
      const transport = transportRef.current;
      if (!transport?.isOpen) return;
      transport.send(toolConfigPayload(pendingToolNamesRef.current.names, pendingToolNamesRef.current.roleId));
    };
    resolveConfirmationRef.current = (approved: boolean) => {
      const pending = pendingConfirmationRef.current;
      const transport = transportRef.current;
      if (!pending || !transport?.isOpen) return;
      if (Date.parse(pending.expiresAt) <= Date.now()) {
        pendingConfirmationRef.current = null;
        setPendingConfirmation(null);
        setCaption("该确认已过期，请重新发起操作");
        return;
      }
      transport.send(confirmationDecisionPayload(pending, approved));
    };

    rafRef.current = requestAnimationFrame(tickLevel);
    const handleVisibilityChange = () => {
      if (document.visibilityState !== "hidden") {
        if (hiddenCaptureTimer) clearTimeout(hiddenCaptureTimer);
        hiddenCaptureTimer = null;
        return;
      }
      if (!micActiveRef.current || hiddenCaptureTimer) return;
      hiddenCaptureTimer = setTimeout(() => {
        hiddenCaptureTimer = null;
        if (document.visibilityState === "hidden" && micActiveRef.current) {
          inputGraph.failActiveCapture("页面长时间处于后台，麦克风缓冲已清除");
        }
      }, HIDDEN_CAPTURE_TIMEOUT_MS);
    };
    function createTransport(url: string) {
      const transport = new BrowserVoiceSessionTransport({
      url,
      controller: voiceControllerRef.current,
      onConnectionState: setConnection,
      onFrame: handleFrame,
      onOpen: () => {
        const ttsConfig = pendingTtsConfigRef.current;
        if (ttsConfig) {
          transport.send(ttsConfigPayload(
            ttsConfig.provider,
            ttsConfig.voice,
            ttsConfig.speechRate,
            ttsConfig.dialect,
          ));
        }
        if (pendingAvatarPersonaRef.current !== undefined) {
          const selection = pendingAvatarPersonaRef.current;
          transport.send(avatarPersonaConfigPayload(selection.avatarId, selection.personaId));
        }
        if (pendingToolNamesRef.current !== undefined) {
          transport.send(toolConfigPayload(pendingToolNamesRef.current.names, pendingToolNamesRef.current.roleId));
        }
      },
      onDisconnected: () => {
        // Recovery must re-emit any still-authoritative confirmation.
        pendingConfirmationRef.current = null;
        setPendingConfirmation(null);
        outputGraph.reset();
        avatarAudioSinkRef.current?.reset();
        inputGraph.resetForDisconnect();
      },
      });
      return transport;
    }
    document.addEventListener("visibilitychange", handleVisibilityChange);
    if (!publicVoiceEnabled) {
      const transport = createTransport(`ws://${location.hostname}:8765`);
      transportRef.current = transport;
      transport.start();
    }

    return () => {
      sessionOutputEnabledRef.current = false;
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      if (fallbackTimerRef.current) clearTimeout(fallbackTimerRef.current);
      if (playbackInactivityTimerRef.current) {
        clearTimeout(playbackInactivityTimerRef.current);
      }
      if (thinkingTimerRef.current) clearTimeout(thinkingTimerRef.current);
      if (hiddenCaptureTimer) clearTimeout(hiddenCaptureTimer);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      transportRef.current?.dispose();
      transportRef.current = null;
      stopMic();
      outputGraph.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const start = useCallback((provider?: TtsConfigFrame["provider"]) => startRef.current(provider), []);
  const prepareAdmission = useCallback((admission: typeof preparedAdmissionRef.current) => {
    preparedAdmissionRef.current = admission;
  }, []);
  const retryConnection = useCallback(() => retryConnectionRef.current(), []);
  const stop = useCallback(() => stopRef.current(), []);
  const terminate = useCallback(() => terminateRef.current(), []);
  const clearConversationDisplay = useCallback(() => {
    assistantCaptionRef.current = { text: "", spokenGeneration: null };
    assistantOutputTextRef.current = { generation: null, display: "", spoken: "" };
    setCaption("");
    setTranscript([]);
  }, []);
  const sendText = useCallback((text: string) => sendTextRef.current(text), []);
  const unlockAudioOutput = useCallback(() => unlockAudioOutputRef.current(), []);
  const stopReply = useCallback(() => stopReplyRef.current(), []);
  const setNoiseSuppression = useCallback(
    (enabled: boolean) => setNoiseSuppressionRef.current(enabled),
    [],
  );
  const setBargeInMuted = useCallback((muted: boolean) => setBargeInMutedRef.current(muted), []);
  const setVolume = useCallback((volume: number) => setVolumeRef.current(volume), []);
  const configureTts = useCallback(
    (provider: TtsConfigFrame["provider"], voice: string, speechRate: number, dialect: TtsConfigFrame["dialect"]) => (
      configureTtsRef.current(provider, voice, speechRate, dialect)
    ),
    [],
  );
  const configureAvatarPersona = useCallback(
    (avatarId: string | null, personaId?: string | null) => (
      configureAvatarPersonaRef.current(avatarId, personaId)
    ),
    [],
  );
  const configureTools = useCallback(
    (toolNames: string[], roleId?: string | null) => configureToolsRef.current(toolNames, roleId),
    [],
  );
  const setAvatarAudioSink = useCallback((sink: AvatarAudioSink | null) => {
    avatarAudioSinkRef.current = sink;
    sink?.setVolume(outputVolumeRef.current);
  }, []);
  const resolveConfirmation = useCallback(
    (approved: boolean) => resolveConfirmationRef.current(approved),
    [],
  );

  return {
    state,
    level,
    caption,
    transcript,
    connection,
    sessionId,
    micActive,
    micAvailable,
    ttsConfigurable,
    ttsPreviewAvailable,
    ttsConfigStatus,
    sessionError,
    credentialSummary,
    trialSecondsRemaining,
    prepareAdmission,
    pendingConfirmation,
    start,
    unlockAudioOutput,
    retryConnection,
    stop,
    terminate,
    clearConversationDisplay,
    sendText,
    stopReply,
    setNoiseSuppression,
    setBargeInMuted,
    setVolume,
    configureTts,
    configureAvatarPersona,
    configureTools,
    setAvatarAudioSink,
    resolveConfirmation,
  };
}

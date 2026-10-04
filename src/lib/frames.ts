// Browser-side mirror of server/transport/frames.py's WebSocket schema.
// Keep transport direction explicit: names are always from the browser's view.

import type { InputCaptureDiagnostic, VoiceSessionPhase } from "@/voice/protocol/v2";

export interface UserTextFrame {
  type: "user_text";
  text: string;
}

export interface CancelAssistantResponseFrame {
  type: "cancel_assistant_response";
}

export interface SessionHelloFrame {
  type: "session_hello";
  resume_session_id: string | null;
  resume_token?: string | null;
  supported_protocol_versions?: number[];
  last_session_sequence?: number;
  last_journal_sequence?: number;
  previous_voice_session_id?: string;
  requested_thread_id?: string;
}

export interface PlaybackProgressFrame {
  type: "playback_progress";
  generation: number;
  finished: boolean;
  started?: boolean;
  stopped?: boolean;
  played_audio_end_us?: number;
}

export interface PlaybackQualityFrame {
  type: "playback_quality";
  generation: number;
  arrival_jitter_ms: number;
  max_chunk_gap_ms: number;
  underrun_count: number;
  underrun_total_ms: number;
  chunk_count: number;
}

export interface ClientConnectionQualityFrame {
  type: "client_connection_quality";
  reconnect_count: number;
  last_disconnect_ms: number;
  max_disconnect_ms: number;
}

export interface TtsConfigFrame {
  type: "tts_config";
  provider: "bailian" | "doubao";
  voice: string;
  speech_rate: number;
  dialect: "" | "anhui" | "cantonese" | "dongbei" | "henan" | "hunan" | "shaanxi" | "shandong" | "sichuan";
}

export interface AvatarPersonaConfigFrame {
  type: "avatar_persona_config";
  avatar_id: string | null;
  persona_id: string | null;
}

export interface ToolConfigFrame {
  type: "tool_config";
  tool_names: string[];
  role_id?: string | null;
}

export interface ConfirmationDecisionFrame {
  type: "confirmation_decision";
  confirmation_id: string;
  action_digest: string;
  approved: boolean;
}

export type ClientToServerFrame =
  | UserTextFrame
  | CancelAssistantResponseFrame
  | SessionHelloFrame
  | PlaybackProgressFrame
  | PlaybackQualityFrame
  | ClientConnectionQualityFrame
  | TtsConfigFrame
  | AvatarPersonaConfigFrame
  | ToolConfigFrame
  | ConfirmationDecisionFrame
  | InputCaptureDiagnostic;

export interface UserTranscriptFrame {
  type: "user_transcript";
  text: string;
  generation?: number | null;
  is_final: boolean;
  turn_id?: string | null;
  transcript_revision?: number | null;
}

export interface AssistantTextFrame {
  type: "assistant_text";
  text: string;
  generation: number;
  emotion?: string | null;
  gesture?: string | null;
}

export interface AssistantSpeechTextFrame {
  type: "assistant_speech_text";
  text: string;
  generation: number;
}

export interface AssistantTextAlignmentFrame {
  type: "assistant_text_alignment";
  generation: number;
  speech_id: string;
  text: string;
  audio_start_us: number;
  audio_end_us: number;
}

export interface AssistantAudioFrame {
  type: "assistant_audio";
  pcm16_base64: string;
  sample_rate_hz: number;
  generation: number;
}

export interface AssistantAudioChunkFrame {
  type: "assistant_audio_chunk";
  pcm16_base64: string;
  sample_rate_hz: number;
  generation: number;
  speech_id?: string | null;
  sequence: number;
  is_final: boolean;
}

export interface AssistantResponseCompletedFrame {
  type: "assistant_response_completed";
  generation: number;
}

export type AssistantCancellationReason = "interrupted" | "failed" | "cancelled";

export interface AssistantSpeechCancelledFrame {
  type: "assistant_speech_cancelled";
  generation: number;
  reason?: AssistantCancellationReason;
}

export interface SessionAckFrame {
  type: "session_ack";
  session_id: string;
  resumed: boolean;
  protocol_version?: number;
  resume_token?: string | null;
  thread_id?: string | null;
  previous_voice_session_id?: string | null;
}

export interface InputAudioAckFrame {
  type: "input_audio_ack";
  input_epoch: string;
  highest_contiguous_sequence: number;
  next_start_sample: number;
}

export interface AudioGapFrame {
  type: "audio_gap";
  input_epoch: string;
  expected_sequence: number;
  received_sequence: number;
  expected_start_sample: number;
  received_start_sample: number;
}

export interface VoiceSessionReadyFrame {
  type: "voice_session_ready";
  session_sequence: number;
  input_epoch: string;
}

export interface VoiceSessionPhaseChangedFrame {
  type: "voice_session_phase_changed";
  session_sequence: number;
  from_phase: VoiceSessionPhase;
  to_phase: VoiceSessionPhase;
}

export interface VoiceSessionSnapshotFrame {
  type: "voice_session_snapshot";
  session_sequence: number;
  journal_sequence: number;
  generation: number;
  phase: VoiceSessionPhase;
  active_work_refs: string[];
  pending_confirmation_id?: string | null;
  playback_generation?: number | null;
  played_position_samples?: number | null;
}

export interface VoiceSessionEventTailFrame {
  type: "voice_session_event_tail";
  resume_from_sequence: number;
  through_sequence: number;
  events: Array<VoiceSessionReadyFrame | VoiceSessionPhaseChangedFrame>;
}

export interface VoiceSessionFailureFrame {
  type: "voice_session_failed";
  error_id: string;
  code: string;
  phase: string;
  retryable: boolean;
  retry_after_ms?: number | null;
  session_disposition: "keep_reconnecting" | "close" | "continuation_required";
  safe_message: string;
}

export interface SessionCapabilitiesFrame {
  type: "session_capabilities";
  server_asr: boolean;
  server_tts: boolean;
  assistant_text_streaming?: boolean;
  user_transcript_streaming?: boolean;
  tts_configurable?: boolean;
  tts_preview?: boolean;
}

export interface TtsConfigAckFrame {
  type: "tts_config_ack";
  provider?: "bailian" | "doubao";
  voice?: string;
  speech_rate?: number;
  dialect?: "" | "anhui" | "cantonese" | "dongbei" | "henan" | "hunan" | "shaanxi" | "shandong" | "sichuan";
  applied: boolean;
  error?: string | null;
}

export interface ConfirmationRequestedFrame {
  type: "confirmation_requested";
  confirmation_id: string;
  action_digest: string;
  summary: string;
  required_channel: "voice" | "strong";
  expires_at: string;
  generation: number;
}

export interface ConfirmationResolutionFrame {
  type: "confirmation_resolution";
  confirmation_id: string;
  applied: boolean;
  approved: boolean;
  success: boolean;
  message: string;
  error?: string | null;
}

export type ServerToClientFrame =
  | UserTranscriptFrame
  | AssistantTextFrame
  | AssistantSpeechTextFrame
  | AssistantTextAlignmentFrame
  | AssistantAudioFrame
  | AssistantAudioChunkFrame
  | AssistantResponseCompletedFrame
  | AssistantSpeechCancelledFrame
  | SessionAckFrame
  | InputAudioAckFrame
  | AudioGapFrame
  | VoiceSessionReadyFrame
  | VoiceSessionPhaseChangedFrame
  | VoiceSessionSnapshotFrame
  | VoiceSessionEventTailFrame
  | VoiceSessionFailureFrame
  | SessionCapabilitiesFrame
  | TtsConfigAckFrame
  | ConfirmationRequestedFrame
  | ConfirmationResolutionFrame;

type UnknownFrame = Record<string, unknown>;

function isRecord(value: unknown): value is UnknownFrame {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isSha256(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
}

function isVoiceSessionPhase(value: unknown): value is VoiceSessionPhase {
  return (
    value === "inactive"
    || value === "starting"
    || value === "active"
    || value === "reconnecting"
    || value === "stopping"
    || value === "closed"
  );
}

function isOptionalBoolean(frame: UnknownFrame, key: string): boolean {
  return frame[key] === undefined || typeof frame[key] === "boolean";
}

function isOptionalStringOrNull(frame: UnknownFrame, key: string): boolean {
  return frame[key] === undefined || frame[key] === null || typeof frame[key] === "string";
}

function isOptionalNumberOrNull(frame: UnknownFrame, key: string): boolean {
  return frame[key] === undefined || frame[key] === null || isNumber(frame[key]);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isVisibleVoiceSessionEvent(
  value: unknown,
): value is VoiceSessionReadyFrame | VoiceSessionPhaseChangedFrame {
  const parsed = parseServerFrame(value);
  return parsed?.type === "voice_session_ready"
    || parsed?.type === "voice_session_phase_changed";
}

export function parseServerFrame(value: unknown): ServerToClientFrame | null {
  if (!isRecord(value) || typeof value.type !== "string") return null;

  switch (value.type) {
    case "session_ack":
      return (
        typeof value.session_id === "string"
        && typeof value.resumed === "boolean"
        && isOptionalNumberOrNull(value, "protocol_version")
        && isOptionalStringOrNull(value, "resume_token")
        && isOptionalStringOrNull(value, "thread_id")
        && isOptionalStringOrNull(value, "previous_voice_session_id")
      )
        ? value as unknown as SessionAckFrame
        : null;
    case "input_audio_ack":
      return (
        typeof value.input_epoch === "string"
        && isNumber(value.highest_contiguous_sequence)
        && isNumber(value.next_start_sample)
      ) ? value as unknown as InputAudioAckFrame : null;
    case "audio_gap":
      return (
        typeof value.input_epoch === "string"
        && isNumber(value.expected_sequence)
        && isNumber(value.received_sequence)
        && isNumber(value.expected_start_sample)
        && isNumber(value.received_start_sample)
      ) ? value as unknown as AudioGapFrame : null;
    case "voice_session_ready":
      return (
        isNumber(value.session_sequence)
        && typeof value.input_epoch === "string"
      ) ? value as unknown as VoiceSessionReadyFrame : null;
    case "voice_session_phase_changed":
      return (
        isNumber(value.session_sequence)
        && isVoiceSessionPhase(value.from_phase)
        && isVoiceSessionPhase(value.to_phase)
      ) ? value as unknown as VoiceSessionPhaseChangedFrame : null;
    case "voice_session_snapshot":
      return (
        isNumber(value.session_sequence)
        && isNumber(value.journal_sequence)
        && isNumber(value.generation)
        && isVoiceSessionPhase(value.phase)
        && isStringArray(value.active_work_refs)
        && isOptionalStringOrNull(value, "pending_confirmation_id")
        && isOptionalNumberOrNull(value, "playback_generation")
        && isOptionalNumberOrNull(value, "played_position_samples")
      ) ? value as unknown as VoiceSessionSnapshotFrame : null;
    case "voice_session_event_tail": {
      if (
        !isNumber(value.resume_from_sequence)
        || !isNumber(value.through_sequence)
        || value.through_sequence < value.resume_from_sequence
        || !Array.isArray(value.events)
        || !value.events.every(isVisibleVoiceSessionEvent)
      ) return null;
      let previous = value.resume_from_sequence;
      for (const event of value.events) {
        if (!isRecord(event) || !isNumber(event.session_sequence)) return null;
        if (
          event.session_sequence <= previous
          || event.session_sequence > value.through_sequence
        ) return null;
        previous = event.session_sequence;
      }
      return value as unknown as VoiceSessionEventTailFrame;
    }
    case "voice_session_failed":
      return (
        typeof value.error_id === "string"
        && typeof value.code === "string"
        && typeof value.phase === "string"
        && typeof value.retryable === "boolean"
        && isOptionalNumberOrNull(value, "retry_after_ms")
        && (
          value.session_disposition === "keep_reconnecting"
          || value.session_disposition === "close"
          || value.session_disposition === "continuation_required"
        )
        && typeof value.safe_message === "string"
      ) ? value as unknown as VoiceSessionFailureFrame : null;
    case "session_capabilities":
      return (
        typeof value.server_asr === "boolean"
        && typeof value.server_tts === "boolean"
        && isOptionalBoolean(value, "assistant_text_streaming")
        && isOptionalBoolean(value, "user_transcript_streaming")
        && isOptionalBoolean(value, "tts_configurable")
        && isOptionalBoolean(value, "tts_preview")
      ) ? value as unknown as SessionCapabilitiesFrame : null;
    case "tts_config_ack":
      return (
        typeof value.applied === "boolean"
        && isOptionalStringOrNull(value, "error")
        && (value.provider === undefined || value.provider === "bailian" || value.provider === "doubao")
        && isOptionalStringOrNull(value, "voice")
        && isOptionalNumberOrNull(value, "speech_rate")
      ) ? value as unknown as TtsConfigAckFrame : null;
    case "confirmation_requested":
      return (
        typeof value.confirmation_id === "string"
        && isSha256(value.action_digest)
        && typeof value.summary === "string"
        && (value.required_channel === "voice" || value.required_channel === "strong")
        && typeof value.expires_at === "string"
        && !Number.isNaN(Date.parse(value.expires_at))
        && isNumber(value.generation)
      ) ? value as unknown as ConfirmationRequestedFrame : null;
    case "confirmation_resolution":
      return (
        typeof value.confirmation_id === "string"
        && typeof value.applied === "boolean"
        && typeof value.approved === "boolean"
        && typeof value.success === "boolean"
        && typeof value.message === "string"
        && isOptionalStringOrNull(value, "error")
      ) ? value as unknown as ConfirmationResolutionFrame : null;
    case "user_transcript":
      return (
        typeof value.text === "string"
        && typeof value.is_final === "boolean"
        && isOptionalNumberOrNull(value, "generation")
        && isOptionalStringOrNull(value, "turn_id")
        && isOptionalNumberOrNull(value, "transcript_revision")
      ) ? value as unknown as UserTranscriptFrame : null;
    case "assistant_text":
      return (
        typeof value.text === "string"
        && isNumber(value.generation)
        && isOptionalStringOrNull(value, "speech_id")
        && isOptionalStringOrNull(value, "emotion")
        && isOptionalStringOrNull(value, "gesture")
      ) ? value as unknown as AssistantTextFrame : null;
    case "assistant_speech_text":
      return typeof value.text === "string" && isNumber(value.generation)
        ? value as unknown as AssistantSpeechTextFrame
        : null;
    case "assistant_text_alignment":
      return typeof value.text === "string" && isNumber(value.generation)
        && typeof value.speech_id === "string" && value.speech_id.length > 0
        && isNumber(value.audio_start_us) && value.audio_start_us >= 0
        && isNumber(value.audio_end_us) && value.audio_end_us >= value.audio_start_us
        ? value as unknown as AssistantTextAlignmentFrame : null;
    case "assistant_audio":
      return (
        typeof value.pcm16_base64 === "string"
        && isNumber(value.sample_rate_hz)
        && isNumber(value.generation)
      ) ? value as unknown as AssistantAudioFrame : null;
    case "assistant_audio_chunk":
      return (
        typeof value.pcm16_base64 === "string"
        && isNumber(value.sample_rate_hz)
        && isNumber(value.generation)
        && isNumber(value.sequence)
        && typeof value.is_final === "boolean"
      ) ? value as unknown as AssistantAudioChunkFrame : null;
    case "assistant_response_completed":
      return isNumber(value.generation)
        ? value as unknown as AssistantResponseCompletedFrame
        : null;
    case "assistant_speech_cancelled":
      return (
        isNumber(value.generation)
        && (
          value.reason === undefined
          || value.reason === "interrupted"
          || value.reason === "failed"
          || value.reason === "cancelled"
        )
      ) ? value as unknown as AssistantSpeechCancelledFrame : null;
    default:
      return null;
  }
}

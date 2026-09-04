export type CaptureMode = "prebuffer" | "live";

export interface DeviceCaptureProfile {
  profile_version: number;
  max_buffer_ms: number;
  silence_threshold: number;
  pre_roll_ms: number;
  frame_duration_ms: number;
  max_replay_rate: number;
  catchup_deadline_ms: number;
  queue_low_watermark: number;
  queue_high_watermark: number;
}

export const DEFAULT_DEVICE_CAPTURE_PROFILE: DeviceCaptureProfile = {
  profile_version: 1,
  max_buffer_ms: 30_000,
  silence_threshold: 0.003,
  pre_roll_ms: 100,
  frame_duration_ms: 32,
  max_replay_rate: 2,
  catchup_deadline_ms: 30_000,
  queue_low_watermark: 8,
  queue_high_watermark: 32,
};

export interface DeviceCaptureConstraints {
  echo_cancellation: boolean | null;
  noise_suppression: boolean | null;
  auto_gain_control: boolean | null;
}

export interface DeviceCaptureEffectOwners {
  echo_cancellation: "device" | "none";
  noise_suppression: "device" | "none";
  auto_gain_control: "device" | "none";
}

export interface InputEpochStarted {
  type: "input_epoch_started";
  input_epoch: string;
  format: {
    format_id: string;
    encoding: "pcm_s16le";
    sample_rate_hz: number;
    channels: number;
  };
  requested_profile: DeviceCaptureProfile;
  effective_profile: DeviceCaptureProfile;
  timeline_origin_ms: number;
  requested_constraints: DeviceCaptureConstraints;
  effective_constraints: DeviceCaptureConstraints;
  effect_owners: DeviceCaptureEffectOwners;
}

export interface InputAudioFrame {
  type: "input_audio_frame";
  input_epoch: string;
  sequence: number;
  start_sample: number;
  sample_count: number;
  capture_mode: CaptureMode;
  pcm16_base64: string;
}

export interface InputAudioAck {
  type: "input_audio_ack";
  input_epoch: string;
  highest_contiguous_sequence: number;
  next_start_sample: number;
}

export interface InputCaptureDiagnostic {
  type: "input_capture_diagnostic";
  input_epoch: string;
  outcome: "overflow" | "catchup_deadline" | "audio_gap" | "worklet_failure";
  buffered_frames: number;
  buffered_duration_ms: number;
  aggregate_energy: number;
}

export interface AudioGap {
  type: "audio_gap";
  input_epoch: string;
  expected_sequence: number;
  received_sequence: number;
  expected_start_sample: number;
  received_start_sample: number;
}

export interface PlaybackProgressV2 {
  type: "playback_progress_v2";
  output_epoch: string;
  speech_id: string;
  generation: number;
  phase: "started" | "stopped" | "finished";
  played_position_samples: number;
}

export interface SessionHelloV2 {
  type: "session_hello";
  supported_protocol_versions: [2];
  resume_session_id: string | null;
  resume_token: string | null;
  last_session_sequence: number;
  last_journal_sequence: number;
  playback?: { generation: number; played_position_samples: number };
  previous_voice_session_id?: string;
  requested_thread_id?: string;
}

export interface SessionAckV2 {
  type: "session_ack";
  session_id: string;
  resume_token: string;
  resumed: boolean;
  protocol_version: 2;
  thread_id?: string;
  previous_voice_session_id?: string | null;
}

export type VoiceSessionPhase =
  | "inactive"
  | "starting"
  | "active"
  | "reconnecting"
  | "stopping"
  | "closed";

export interface VoiceSessionReadyEvent {
  type: "voice_session_ready";
  session_sequence: number;
  input_epoch: string;
}

export interface VoiceSessionPhaseChangedEvent {
  type: "voice_session_phase_changed";
  session_sequence: number;
  from_phase: VoiceSessionPhase;
  to_phase: VoiceSessionPhase;
}

export type VoiceSessionEvent = VoiceSessionReadyEvent | VoiceSessionPhaseChangedEvent;

export interface VoiceSessionSnapshot {
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

export interface VoiceSessionEventTail {
  type: "voice_session_event_tail";
  resume_from_sequence: number;
  through_sequence: number;
  events: VoiceSessionEvent[];
}

import type {
  DeviceAudioInputEpochOptions,
  DeviceAudioInputRuntime,
} from "../audio/input-runtime";
import type { DeviceAudioOutputRuntime } from "../audio/output-runtime";
import type {
  InputEpochStarted,
  SessionAckV2,
  SessionHelloV2,
  VoiceSessionEvent,
  VoiceSessionEventTail,
  VoiceSessionPhase,
  VoiceSessionSnapshot,
} from "../protocol/v2";

export interface ClientVoiceSessionControllerOptions {
  input: DeviceAudioInputRuntime;
  output: DeviceAudioOutputRuntime;
  providers?: { asr?: "doubao" | "dashscope" | null; llm?: "deepseek" | "openai" | null };
}

export class ClientVoiceSessionController {
  private readonly input: DeviceAudioInputRuntime;
  private readonly output: DeviceAudioOutputRuntime;
  private readonly providers: ClientVoiceSessionControllerOptions["providers"];
  private sessionId: string | null = null;
  private resumeToken: string | null = null;
  private threadId: string | null = null;
  private previousVoiceSessionId: string | null = null;
  private inputEpoch: string | null = null;
  private lastSessionSequence = 0;
  private lastJournalSequence = 0;
  private playback: { generation: number; played_position_samples: number } | undefined;
  private currentPhase: VoiceSessionPhase = "inactive";

  constructor(options: ClientVoiceSessionControllerOptions) {
    this.input = options.input;
    this.output = options.output;
    this.providers = options.providers;
  }

  get phase(): VoiceSessionPhase {
    return this.currentPhase;
  }

  createHello(): SessionHelloV2 {
    return {
      type: "session_hello",
      supported_protocol_versions: [2],
      resume_session_id: this.sessionId,
      resume_token: this.resumeToken,
      last_session_sequence: this.lastSessionSequence,
      last_journal_sequence: this.lastJournalSequence,
      ...(this.providers?.asr ? { asr_provider: this.providers.asr } : {}),
      ...(this.providers?.llm ? { llm_provider: this.providers.llm } : {}),
      ...(this.playback === undefined ? {} : { playback: this.playback }),
      ...(this.previousVoiceSessionId === null
        ? {}
        : {
            previous_voice_session_id: this.previousVoiceSessionId,
            requested_thread_id: this.threadId ?? this.previousVoiceSessionId,
          }),
    };
  }

  acceptSession(ack: SessionAckV2): void {
    this.sessionId = ack.session_id;
    this.resumeToken = ack.resume_token;
    this.threadId = ack.thread_id ?? ack.session_id;
    this.previousVoiceSessionId = null;
    this.currentPhase = ack.resumed ? "reconnecting" : "starting";
  }

  beginInput(
    inputEpoch: string,
    options: DeviceAudioInputEpochOptions = {},
  ): InputEpochStarted {
    this.inputEpoch = inputEpoch;
    return this.input.beginEpoch(inputEpoch, options);
  }

  applyEvent(event: VoiceSessionEvent): void {
    if (event.session_sequence <= this.lastSessionSequence) return;
    this.lastSessionSequence = event.session_sequence;
    if (event.type === "voice_session_phase_changed") {
      this.currentPhase = event.to_phase;
      return;
    }
    if (event.input_epoch === this.inputEpoch && this.input.state === "buffering") {
      this.input.release(event.input_epoch);
      this.currentPhase = "active";
    }
  }

  applySnapshot(snapshot: VoiceSessionSnapshot): void {
    if (snapshot.session_sequence < this.lastSessionSequence) return;
    this.lastSessionSequence = snapshot.session_sequence;
    this.lastJournalSequence = snapshot.journal_sequence;
    this.currentPhase = snapshot.phase;
    if (
      snapshot.playback_generation != null
      && snapshot.played_position_samples != null
    ) {
      this.observePlayback(
        snapshot.playback_generation,
        snapshot.played_position_samples,
      );
    }
  }

  applyEventTail(tail: VoiceSessionEventTail): void {
    if (tail.through_sequence <= this.lastSessionSequence) return;
    if (tail.resume_from_sequence > this.lastSessionSequence) return;
    for (const event of tail.events) this.applyEvent(event);
    this.lastSessionSequence = Math.max(
      this.lastSessionSequence,
      tail.through_sequence,
    );
  }

  beginContinuation(): void {
    if (this.sessionId === null) return;
    this.previousVoiceSessionId = this.sessionId;
    this.threadId ??= this.sessionId;
    this.sessionId = null;
    this.resumeToken = null;
    this.lastSessionSequence = 0;
    this.lastJournalSequence = 0;
    this.playback = undefined;
    this.currentPhase = "starting";
  }

  startNewSession(): void {
    this.sessionId = null;
    this.resumeToken = null;
    this.threadId = null;
    this.previousVoiceSessionId = null;
    this.inputEpoch = null;
    this.lastSessionSequence = 0;
    this.lastJournalSequence = 0;
    this.playback = undefined;
    this.currentPhase = "inactive";
    this.input.reset();
    this.output.reset();
  }

  observeJournal(sequence: number): void {
    this.lastJournalSequence = Math.max(this.lastJournalSequence, sequence);
  }

  observePlayback(generation: number, playedPositionSamples: number): void {
    this.playback = {
      generation,
      played_position_samples: Math.max(0, playedPositionSamples),
    };
  }

  disconnected(): void {
    this.currentPhase = "reconnecting";
    this.input.reset();
    this.output.reset();
    this.inputEpoch = null;
  }
}

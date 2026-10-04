import { describe, expect, it } from "vitest";

import { DeviceAudioInputRuntime } from "../audio/input-runtime";
import { DeviceAudioOutputRuntime } from "../audio/output-runtime";
import { ClientVoiceSessionController } from "./controller";


describe("ClientVoiceSessionController", () => {
  it("restores a historical thread without persisting or replaying resume credentials", () => {
    const controller = new ClientVoiceSessionController({ input: new DeviceAudioInputRuntime(), output: new DeviceAudioOutputRuntime(),
      continuation: { threadId: "thread-history", voiceSessionId: "voice-history" } });
    expect(controller.createHello()).toMatchObject({ previous_voice_session_id: "voice-history", requested_thread_id: "thread-history", resume_token: null, resume_session_id: null });
    controller.acceptSession({ type: "session_ack", session_id: "voice-next", thread_id: "thread-history", protocol_version: 2, resumed: false, resume_token: "new-secret" });
    expect(controller.continuationIdentity).toEqual({ threadId: "thread-history", voiceSessionId: "voice-next" });
    controller.beginContinuation();
    expect(controller.createHello()).toMatchObject({ previous_voice_session_id: "voice-next", requested_thread_id: "thread-history", resume_token: null });
    controller.startNewSession();
    expect(controller.continuationIdentity).toBeNull();
    expect(controller.createHello().requested_thread_id).toBeUndefined();
  });
  it("sends optional role providers in the session hello", () => {
    const controller = new ClientVoiceSessionController({
      input: new DeviceAudioInputRuntime(), output: new DeviceAudioOutputRuntime(),
      providers: { asr: "dashscope", llm: "openai" },
    });
    expect(controller.createHello()).toMatchObject({ asr_provider: "dashscope", llm_provider: "openai" });
  });
  it("starts a new public voice conversation without reusing the previous resume token", () => {
    const controller = new ClientVoiceSessionController({
      input: new DeviceAudioInputRuntime({ maxBufferFrames: 8 }),
      output: new DeviceAudioOutputRuntime(),
    });
    controller.acceptSession({
      type: "session_ack", session_id: "old", resume_token: "old-token",
      resumed: false, protocol_version: 2,
    });
    controller.observeJournal(12);
    controller.startNewSession();
    expect(controller.createHello()).toMatchObject({
      resume_session_id: null, resume_token: null,
      last_session_sequence: 0, last_journal_sequence: 0,
    });
  });

  it("releases only the matching input epoch and builds semantic resume state", () => {
    const input = new DeviceAudioInputRuntime({ maxBufferFrames: 8 });
    const output = new DeviceAudioOutputRuntime();
    const controller = new ClientVoiceSessionController({ input, output });
    controller.acceptSession({
      type: "session_ack",
      session_id: "voice-1",
      resume_token: "token-1",
      resumed: false,
      protocol_version: 2,
    });
    controller.beginInput("input-1");
    input.pushFrame(new Int16Array(512));

    controller.applyEvent({
      type: "voice_session_ready",
      session_sequence: 1,
      input_epoch: "stale-input",
    });
    expect(input.state).toBe("buffering");
    controller.applyEvent({
      type: "voice_session_ready",
      session_sequence: 2,
      input_epoch: "input-1",
    });
    expect(input.state).toBe("replaying");

    controller.observeJournal(17);
    controller.observePlayback(7, 4096);
    controller.disconnected();

    expect(controller.phase).toBe("reconnecting");
    expect(input.state).toBe("reset");
    expect(controller.createHello()).toEqual({
      type: "session_hello",
      supported_protocol_versions: [2],
      resume_session_id: "voice-1",
      resume_token: "token-1",
      last_session_sequence: 2,
      last_journal_sequence: 17,
      playback: { generation: 7, played_position_samples: 4096 },
    });
  });

  it("applies a semantic snapshot and advances across a filtered event tail", () => {
    const input = new DeviceAudioInputRuntime({ maxBufferFrames: 8 });
    const controller = new ClientVoiceSessionController({
      input,
      output: new DeviceAudioOutputRuntime(),
    });
    controller.acceptSession({
      type: "session_ack",
      session_id: "voice-1",
      resume_token: "token-2",
      resumed: true,
      protocol_version: 2,
    });

    controller.applySnapshot({
      type: "voice_session_snapshot",
      session_sequence: 8,
      journal_sequence: 21,
      generation: 4,
      phase: "reconnecting",
      active_work_refs: [],
    });
    controller.applyEventTail({
      type: "voice_session_event_tail",
      resume_from_sequence: 8,
      through_sequence: 10,
      events: [{
        type: "voice_session_phase_changed",
        session_sequence: 9,
        from_phase: "active",
        to_phase: "reconnecting",
      }],
    });

    expect(controller.phase).toBe("reconnecting");
    expect(controller.createHello()).toMatchObject({
      last_session_sequence: 10,
      last_journal_sequence: 21,
    });
  });

  it("turns a rejected resume into an authorized fresh continuation hello", () => {
    const controller = new ClientVoiceSessionController({
      input: new DeviceAudioInputRuntime({ maxBufferFrames: 8 }),
      output: new DeviceAudioOutputRuntime(),
    });
    controller.acceptSession({
      type: "session_ack",
      session_id: "voice-old",
      resume_token: "token-old",
      resumed: false,
      protocol_version: 2,
      thread_id: "thread-shared",
    });

    controller.beginContinuation();

    expect(controller.createHello()).toEqual({
      type: "session_hello",
      supported_protocol_versions: [2],
      resume_session_id: null,
      resume_token: null,
      previous_voice_session_id: "voice-old",
      requested_thread_id: "thread-shared",
      last_session_sequence: 0,
      last_journal_sequence: 0,
    });
  });
});

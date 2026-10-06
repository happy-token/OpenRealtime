import { describe, expect, it } from "vitest";
import { parseServerFrame } from "./frames";

describe("parseServerFrame", () => {
  it("requires all precise stop identities and preserves legacy cancellation", () => {
    const frame = { type: "assistant_speech_cancelled", generation: 1,
      output_epoch: "epoch", speech_id: "speech", stop_command_id: "stop" };
    expect(parseServerFrame(frame)).toEqual(frame);
    for (const field of ["output_epoch", "speech_id", "stop_command_id"]) {
      expect(parseServerFrame({ ...frame, [field]: null })).toBeNull();
      expect(parseServerFrame({ ...frame, [field]: "" })).toBeNull();
    }
    for (const generation of [-1, 1.5, Number.NaN, Number.POSITIVE_INFINITY]) {
      expect(parseServerFrame({ ...frame, generation })).toBeNull();
    }
    expect(parseServerFrame({ type: frame.type, generation: 1 })).not.toBeNull();
  });

  it("accepts a complete assistant text frame", () => {
    expect(parseServerFrame({
      type: "assistant_text",
      text: "你好",
      generation: 3,
    })).toEqual({
      type: "assistant_text",
      text: "你好",
      generation: 3,
    });
  });

  it("rejects state-changing frames with missing correlation fields", () => {
    expect(parseServerFrame({ type: "assistant_text", text: "你好" })).toBeNull();
    expect(parseServerFrame({ type: "assistant_response_completed" })).toBeNull();
  });

  it("rejects unknown frames instead of silently widening the protocol", () => {
    expect(parseServerFrame({ type: "assistant_magic", generation: 3 })).toBeNull();
    expect(parseServerFrame("not an object")).toBeNull();
  });

  it("preserves a response failure reason for message lifecycle handling", () => {
    expect(parseServerFrame({
      type: "assistant_speech_cancelled",
      generation: 3,
      reason: "failed",
    })).toEqual({
      type: "assistant_speech_cancelled",
      generation: 3,
      reason: "failed",
    });
  });

  it("validates v2 session, input ack, and recovery barrier frames", () => {
    expect(parseServerFrame({
      type: "session_ack",
      session_id: "voice-1",
      resumed: false,
      protocol_version: 2,
      resume_token: "token-1",
    })).not.toBeNull();
    expect(parseServerFrame({
      type: "input_audio_ack",
      input_epoch: "input-1",
      highest_contiguous_sequence: 7,
      next_start_sample: 4096,
    })).not.toBeNull();
    expect(parseServerFrame({
      type: "voice_session_ready",
      session_sequence: 4,
      input_epoch: "input-1",
    })).not.toBeNull();
    expect(parseServerFrame({
      type: "voice_session_ready",
      session_sequence: 4,
    })).toBeNull();
  });

  it("rejects unknown voice session phases", () => {
    expect(parseServerFrame({
      type: "voice_session_phase_changed",
      session_sequence: 5,
      from_phase: "active",
      to_phase: "teleporting",
    })).toBeNull();
  });

  it("validates semantic resume snapshot and bounded event tail frames", () => {
    expect(parseServerFrame({
      type: "voice_session_snapshot",
      session_sequence: 8,
      journal_sequence: 21,
      generation: 4,
      phase: "reconnecting",
      active_work_refs: ["work-1"],
      pending_confirmation_id: null,
      playback_generation: 3,
      played_position_samples: 4096,
    })).not.toBeNull();
    expect(parseServerFrame({
      type: "voice_session_event_tail",
      resume_from_sequence: 8,
      through_sequence: 10,
      events: [{
        type: "voice_session_phase_changed",
        session_sequence: 9,
        from_phase: "active",
        to_phase: "reconnecting",
      }],
    })).not.toBeNull();
    expect(parseServerFrame({
      type: "voice_session_snapshot",
      session_sequence: 8,
      journal_sequence: 21,
      generation: 4,
      phase: "unknown",
    })).toBeNull();
  });

  it("validates bound confirmation request and resolution frames", () => {
    const digest = "a".repeat(64);
    expect(parseServerFrame({
      type: "confirmation_requested",
      confirmation_id: "confirmation-1",
      action_digest: digest,
      summary: "向外部发送消息",
      required_channel: "voice",
      expires_at: "2026-08-20T12:00:00+00:00",
      generation: 3,
    })).not.toBeNull();
    expect(parseServerFrame({
      type: "confirmation_requested",
      confirmation_id: "confirmation-1",
      action_digest: "wrong",
      summary: "向外部发送消息",
      required_channel: "voice",
      expires_at: "2026-08-20T12:00:00+00:00",
      generation: 3,
    })).toBeNull();
    expect(parseServerFrame({
      type: "confirmation_resolution",
      confirmation_id: "confirmation-1",
      applied: true,
      approved: true,
      success: true,
      message: "消息已发送",
      error: null,
    })).not.toBeNull();
  });
});

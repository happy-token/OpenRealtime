import { describe, expect, it } from "vitest";
import {
  DEFAULT_ALLOW_BARGE_IN,
  browserSpeechRecognitionErrorPolicy,
  confirmationDecisionPayload,
  connectionStateForAttempt,
  mergeAssistantTranscript,
  mergeUserTranscript,
  settleAssistantTranscript,
  playbackInactivityFallbackDelayMs,
  playbackProgressPayload,
  shouldOptimisticallyAppendUserTranscript,
  playedAudioEndUs,
  responseCompletionFallbackDelayMs,
  shouldArmTextOnlySpeechFallback,
  speechInputMode,
  shouldDropAudioFrame,
  shouldResetTranscriptForSession,
  startAudioSource,
  ttsConfigPayload,
  updateAssistantCaption,
  updateAssistantOutputText,
  browserSpeechTextForResponse,
  avatarPersonaConfigPayload,
  toolConfigPayload,
} from "./use-voice-session";

describe("voice playback safety defaults", () => {
  it("keeps uploading microphone audio while the assistant is speaking", () => {
    expect(DEFAULT_ALLOW_BARGE_IN).toBe(true);
  });

  it("does not report idle while real server TTS is still starting", () => {
    expect(shouldArmTextOnlySpeechFallback(true)).toBe(false);
    expect(shouldArmTextOnlySpeechFallback(false)).toBe(true);
  });

  it("bounds the replying state even when an audio ended event is lost", () => {
    expect(responseCompletionFallbackDelayMs(true, 7, 7, 2, 3400)).toBe(4600);
    expect(responseCompletionFallbackDelayMs(true, 7, 7, 0, 0)).toBe(1200);
    expect(responseCompletionFallbackDelayMs(true, 8, 7, 2, 3400)).toBeNull();
  });

  it("releases the visual speaking floor when duplex TTS becomes silent", () => {
    expect(playbackInactivityFallbackDelayMs(600)).toBe(1000);
    expect(playbackInactivityFallbackDelayMs(-10)).toBe(400);
  });
});

describe("session TTS selection", () => {
  it("sends the selected provider with its voice configuration", () => {
    expect(ttsConfigPayload("bailian", "longanhuan_v3", 20, "cantonese")).toEqual({
      type: "tts_config",
      provider: "bailian",
      voice: "longanhuan_v3",
      speech_rate: 20,
      dialect: "cantonese",
    });
  });
});

describe("Avatar Persona selection", () => {
  it("sends only stable resource IDs and never browser-authored prompt text", () => {
    expect(avatarPersonaConfigPayload("avatar-zhaoning")).toEqual({
      type: "avatar_persona_config",
      avatar_id: "avatar-zhaoning",
      persona_id: null,
    });
    expect(avatarPersonaConfigPayload(null, "intellectual-warmth")).toEqual({
      type: "avatar_persona_config",
      avatar_id: null,
      persona_id: "intellectual-warmth",
    });
  });
});

describe("role tool selection", () => {
  it("deduplicates canonical function names", () => {
    expect(toolConfigPayload(["search_web", "get_current_datetime", "search_web"])).toEqual({
      type: "tool_config",
      tool_names: ["search_web", "get_current_datetime"],
    });
  });
});

describe("bound confirmation", () => {
  it("echoes the exact server-owned identity and digest", () => {
    expect(confirmationDecisionPayload({
      confirmationId: "confirmation-1",
      actionDigest: "a".repeat(64),
      summary: "向外部发送消息",
      requiredChannel: "voice",
      expiresAt: "2026-08-20T12:00:00+00:00",
      generation: 3,
    }, true)).toEqual({
      type: "confirmation_decision",
      confirmation_id: "confirmation-1",
      action_digest: "a".repeat(64),
      approved: true,
    });
  });
});

describe("user transcript ownership", () => {
  it("keeps browser-ASR fallback visible while server streaming remains authoritative", () => {
    expect(shouldOptimisticallyAppendUserTranscript(false)).toBe(true);
    expect(shouldOptimisticallyAppendUserTranscript(null)).toBe(true);
    expect(shouldOptimisticallyAppendUserTranscript(true)).toBe(false);
  });
});

describe("client playback diagnostics", () => {
  it("registers the ended handler before starting a zero-duration terminal source", () => {
    const calls: string[] = [];
    let ended: (() => void) | null = null;
    const source = {
      addEventListener: (_type: "ended", listener: () => void) => {
        calls.push("listen");
        ended = listener;
      },
      start: () => {
        calls.push("start");
        ended?.();
      },
    };

    startAudioSource(source, 0, () => calls.push("ended"));

    expect(calls).toEqual(["listen", "start", "ended"]);
  });

  it("reports start, stop, and natural finish as distinct events", () => {
    expect(playbackProgressPayload(7, "started")).toEqual({
      type: "playback_progress",
      generation: 7,
      finished: false,
      started: true,
      stopped: false,
    });
    expect(playbackProgressPayload(7, "stopped").stopped).toBe(true);
    expect(playbackProgressPayload(7, "finished").finished).toBe(true);
  });

  it("clamps client playback position to the scheduled audio range", () => {
    expect(playedAudioEndUs(10, 10.125, 10.5)).toBe(125_000);
    expect(playedAudioEndUs(10, 11, 10.5)).toBe(500_000);
    expect(playedAudioEndUs(10, 9.5, 10.5)).toBe(0);
    expect(playbackProgressPayload(7, "stopped", 125_000)).toEqual({
      type: "playback_progress",
      generation: 7,
      finished: false,
      started: false,
      stopped: true,
      played_audio_end_us: 125_000,
    });
  });
});

describe("browserSpeechRecognitionErrorPolicy", () => {
  it("treats permission denial as fatal and tells the user the server ASR path is required", () => {
    expect(browserSpeechRecognitionErrorPolicy("not-allowed")).toEqual({
      fatal: true,
      message: "当前浏览器拒绝语音识别；请启用服务端 ASR，或改用文字输入",
    });
  });
});

describe("connectionStateForAttempt", () => {
  it("stays 'connecting' when a connection has never successfully opened", () => {
    expect(connectionStateForAttempt(false)).toBe("connecting");
  });

  it("becomes 'reconnecting' once a connection has previously opened", () => {
    expect(connectionStateForAttempt(true)).toBe("reconnecting");
  });
});

describe("session transcript ownership", () => {
  it("clears in-memory bubbles when reconnect creates a different server session", () => {
    expect(shouldResetTranscriptForSession("old-session", "new-session")).toBe(true);
    expect(
      shouldResetTranscriptForSession(
        "old-session",
        "new-session",
        "old-session",
      ),
    ).toBe(false);
    expect(shouldResetTranscriptForSession("same-session", "same-session")).toBe(false);
    expect(shouldResetTranscriptForSession(null, "first-session")).toBe(false);
  });
});

describe("shouldDropAudioFrame", () => {
  it("keeps audio when nothing has been cancelled", () => {
    expect(shouldDropAudioFrame(1, null)).toBe(false);
  });

  it("drops a straggler chunk for the cancelled generation", () => {
    // The server stops streaming at a chunk boundary, so one chunk can already
    // be in flight behind the cancel frame. Playing it would put the
    // interrupted assistant's tail after the barge-in.
    expect(shouldDropAudioFrame(2, 2)).toBe(true);
  });

  it("keeps audio for the generation that replaced the cancelled one", () => {
    expect(shouldDropAudioFrame(3, 2)).toBe(false);
  });

  it("keeps audio for an earlier generation than the cancelled one", () => {
    // Generations are monotonic, so this shouldn't happen; asserted so the
    // predicate stays an equality check rather than drifting into `<=`, which
    // would silently mute a legitimate reply.
    expect(shouldDropAudioFrame(1, 2)).toBe(false);
  });

  it("keeps audio when the frame carries no generation", () => {
    expect(shouldDropAudioFrame(undefined, 2)).toBe(false);
  });
});

describe("mergeAssistantTranscript", () => {
  it("updates the same assistant entry for cumulative deltas", () => {
    const first = mergeAssistantTranscript([], 7, "你");

    expect(mergeAssistantTranscript(first, 7, "你好")).toEqual([
      { role: "assistant", text: "你好", generation: 7, status: "streaming" },
    ]);
  });

  it("starts a new entry for a later generation", () => {
    expect(
      mergeAssistantTranscript(
        [{ role: "assistant", text: "旧回答", generation: 7 }],
        8,
        "新回答",
      ),
    ).toEqual([
      { role: "assistant", text: "旧回答", generation: 7 },
      { role: "assistant", text: "新回答", generation: 8, status: "streaming" },
    ]);
  });

  it("updates an existing assistant generation when a user partial arrives between deltas", () => {
    const interleaved = [
      { role: "assistant" as const, text: "我查一下", generation: 7 },
      { role: "user" as const, text: "北京的", generation: 8 },
    ];

    expect(mergeAssistantTranscript(interleaved, 7, "我查一下，马上告诉你")).toEqual([
      {
        role: "assistant",
        text: "我查一下，马上告诉你",
        generation: 7,
        status: "streaming",
      },
      { role: "user", text: "北京的", generation: 8 },
    ]);
  });

  it("repairs duplicate assistant bubbles for the same response generation", () => {
    const duplicated = [
      { role: "assistant" as const, text: "我查一下", generation: 7 },
      { role: "assistant" as const, text: "我查一下，马上", generation: 7 },
    ];

    expect(mergeAssistantTranscript(duplicated, 7, "我查一下，马上告诉你")).toEqual([
      {
        role: "assistant",
        text: "我查一下，马上告诉你",
        generation: 7,
        status: "streaming",
      },
    ]);
  });
});

describe("assistant transcript lifecycle", () => {
  it("marks a streaming assistant message completed at the response boundary", () => {
    const streaming = mergeAssistantTranscript([], 7, "**上海天气**");

    expect(settleAssistantTranscript(streaming, 7, "completed")).toEqual([
      {
        role: "assistant",
        text: "**上海天气**",
        generation: 7,
        status: "completed",
      },
    ]);
  });

  it("keeps an interrupted partial response visibly distinct from a completed reply", () => {
    const streaming = mergeAssistantTranscript([], 7, "我查一下，马上");

    expect(settleAssistantTranscript(streaming, 7, "interrupted")).toEqual([
      {
        role: "assistant",
        text: "我查一下，马上",
        generation: 7,
        status: "interrupted",
      },
    ]);
  });
});

describe("browser TTS text selection", () => {
  it("prefers explicitly supplied spoken content over rich display content", () => {
    const display = updateAssistantOutputText(
      { generation: null, display: "", spoken: "" },
      "display",
      7,
      "**上海天气**：[详情](https://example.com)",
    );
    const spoken = updateAssistantOutputText(display, "spoken", 7, "上海今天多云。\n");

    expect(browserSpeechTextForResponse(spoken, 7)).toBe("上海今天多云。");
  });

  it("converts display Markdown to plain speech when no spoken content arrives", () => {
    const output = updateAssistantOutputText(
      { generation: null, display: "", spoken: "" },
      "display",
      8,
      "## 上海天气\n\n**多云**，查看[详情](https://example.com)",
    );

    expect(browserSpeechTextForResponse(output, 8)).toBe("上海天气 多云，查看详情");
    expect(browserSpeechTextForResponse(output, 9)).toBe("");
  });
});

describe("updateAssistantCaption", () => {
  it("keeps streaming TTS text visible instead of replacing it with richer display text", () => {
    const display = updateAssistantCaption(
      { text: "", spokenGeneration: null },
      { kind: "display", generation: 7, text: "**很久以前**" },
    );
    const spoken = updateAssistantCaption(display, {
      kind: "spoken",
      generation: 7,
      text: "很久以前",
    });

    expect(
      updateAssistantCaption(spoken, {
        kind: "display",
        generation: 7,
        text: "**很久以前**，有一只小鸟",
      }),
    ).toEqual({ text: "很久以前", spokenGeneration: 7 });
  });

  it("allows a new response generation to show display text before its TTS text arrives", () => {
    expect(
      updateAssistantCaption(
        { text: "旧回复", spokenGeneration: 7 },
        { kind: "display", generation: 8, text: "新回复" },
      ),
    ).toEqual({ text: "新回复", spokenGeneration: 7 });
  });
});

describe("mergeUserTranscript", () => {
  it("uses the server turn id so a late ASR revision cannot create a second bubble", () => {
    const partial = mergeUserTranscript([], 3, "今天天气怎么样", {
      turnId: "turn-3",
      revision: 7,
      isFinal: false,
    });

    expect(
      mergeUserTranscript(partial, 4, "今天天气怎么样？", {
        turnId: "turn-3",
        revision: 8,
        isFinal: true,
      }),
    ).toEqual([
      {
        role: "user",
        text: "今天天气怎么样？",
        generation: 4,
        turnId: "turn-3",
        revision: 8,
        isFinal: true,
      },
    ]);
  });

  it("ignores an out-of-order ASR revision for an already newer bubble", () => {
    const current = mergeUserTranscript([], 3, "今天天气怎么样？", {
      turnId: "turn-3",
      revision: 8,
      isFinal: true,
    });

    expect(
      mergeUserTranscript(current, 3, "今天天气怎么样", {
        turnId: "turn-3",
        revision: 7,
        isFinal: false,
      }),
    ).toEqual(current);
  });

  it("binds a server echo to the optimistic text bubble instead of duplicating it", () => {
    expect(
      mergeUserTranscript(
        [{ role: "user", text: "北京天气怎么样？" }],
        3,
        "北京天气怎么样？",
      ),
    ).toEqual([
      { role: "user", text: "北京天气怎么样？", generation: 3 },
    ]);
  });

  it("repairs duplicate user bubbles for the same server turn", () => {
    const duplicated = [
      { role: "user" as const, text: "今天天气", generation: 3, turnId: "turn-3" },
      {
        role: "user" as const,
        text: "今天天气怎么样",
        generation: 3,
        turnId: "turn-3",
      },
    ];

    expect(
      mergeUserTranscript(duplicated, 3, "今天天气怎么样？", {
        turnId: "turn-3",
        revision: 9,
        isFinal: true,
      }),
    ).toEqual([
      {
        role: "user",
        text: "今天天气怎么样？",
        generation: 3,
        turnId: "turn-3",
        revision: 9,
        isFinal: true,
      },
    ]);
  });

  it("updates one user entry as partial ASR text grows", () => {
    const partial = mergeUserTranscript([], 3, "今天北");

    expect(mergeUserTranscript(partial, 3, "今天北京天气怎么样")).toEqual([
      { role: "user", text: "今天北京天气怎么样", generation: 3 },
    ]);
  });

  it("starts a separate entry for another speaker turn", () => {
    expect(
      mergeUserTranscript(
        [{ role: "user", text: "第一位说话人", generation: 3 }],
        4,
        "第二位说话人",
      ),
    ).toEqual([
      { role: "user", text: "第一位说话人", generation: 3 },
      { role: "user", text: "第二位说话人", generation: 4 },
    ]);
  });

  it("updates an existing user generation when an older assistant frame arrives between partials", () => {
    const interleaved = [
      { role: "user" as const, text: "你好呀，今天天气", generation: 5 },
      { role: "user" as const, text: "你好呀，今天天气怎么样呀？", generation: 6 },
      { role: "assistant" as const, text: "请问您想查询哪个城市？", generation: 5 },
    ];

    expect(
      mergeUserTranscript(interleaved, 6, "你好呀，今天天气怎么样呀？北京的"),
    ).toEqual([
      { role: "user", text: "你好呀，今天天气", generation: 5 },
      {
        role: "user",
        text: "你好呀，今天天气怎么样呀？北京的",
        generation: 6,
      },
      { role: "assistant", text: "请问您想查询哪个城市？", generation: 5 },
    ]);
  });
});

describe("speechInputMode", () => {
  it("uses server ASR when the session advertises it", () => {
    expect(speechInputMode(true, true)).toBe("server");
  });

  it("falls back to browser speech recognition without server ASR", () => {
    expect(speechInputMode(false, true)).toBe("browser");
  });

  it("reports unavailable when neither ASR path exists", () => {
    expect(speechInputMode(false, false)).toBe("unavailable");
  });
});

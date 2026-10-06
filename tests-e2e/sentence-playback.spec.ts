import { expect, test } from "@playwright/test";

type Evidence = { sent: Record<string, unknown>[]; sourceEvents: Record<string, unknown>[];
  cleared: unknown[]; inject: (frame: object) => void };
declare global { interface Window { __sentencePlayback: Evidence } }

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("openrealtime-language", "zh-CN");
    const state: Evidence = { sent: [], sourceEvents: [], cleared: [], inject: () => {} };
    window.__sentencePlayback = state;
    let injecting = false;
    const clear = window.clearTimeout.bind(window);
    window.clearTimeout = id => { if (injecting) state.cleared.push(id); clear(id); };
    window.AudioContext = new Proxy(window.AudioContext, { construct(target, args) {
      const context = Reflect.construct(target, args) as AudioContext;
      const create = context.createBufferSource.bind(context);
      context.createBufferSource = () => {
        const source = create();
        const start = source.start.bind(source), stop = source.stop.bind(source);
        source.start = when => { state.sourceEvents.push({ action: "start", when, clock: context.currentTime }); start(when); };
        source.stop = when => { state.sourceEvents.push({ action: "stop", when, clock: context.currentTime }); stop(when); };
        source.addEventListener("ended", () => state.sourceEvents.push({ action: "ended", clock: context.currentTime }));
        return source;
      };
      return context;
    } });
    class Socket {
      readyState = 0;
      listeners = new Map<string, ((event: Event | MessageEvent<string>) => void)[]>();
      constructor() {
        state.inject = frame => { injecting = true; try { this.message(frame); } finally { injecting = false; } };
        setTimeout(() => { this.readyState = 1; this.emit("open", new Event("open")); }, 0);
      }
      addEventListener(type: string, listener: (event: Event | MessageEvent<string>) => void) {
        this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
      }
      emit(type: string, event: Event | MessageEvent<string>) { for (const listener of this.listeners.get(type) ?? []) listener(event); }
      message(frame: object) { this.emit("message", new MessageEvent("message", { data: JSON.stringify(frame) })); }
      send(raw: string) {
        const frame = JSON.parse(raw) as Record<string, unknown>;
        state.sent.push(frame);
        if (frame.type === "session_hello") {
          this.message({ type: "session_ack", session_id: "sentence-e2e", resumed: false,
            protocol_version: 2, resume_token: "token", output_epoch: "epoch" });
          this.message({ type: "session_capabilities", server_asr: false, server_tts: true,
            assistant_text_streaming: true, user_transcript_streaming: false });
        }
      }
      close() { this.readyState = 3; this.emit("close", new Event("close")); }
    }
    window.WebSocket = new Proxy(window.WebSocket, { construct(target, args) {
      const url = new URL(String(args[0]), location.href);
      return url.port === "8765" || url.pathname === "/voice" ? new Socket() : Reflect.construct(target, args);
    } });
    class Recognition { continuous = true; interimResults = true; lang = "zh-CN"; start() {} stop() {} abort() {} }
    Object.assign(window, { SpeechRecognition: Recognition, webkitSpeechRecognition: Recognition });
  });
  await page.goto("/conversation?role_id=e2e-unassigned");
  await page.getByRole("button", { name: "主页开始对话" }).click();
  await expect(page.getByRole("button", { name: "关闭麦克风" })).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.__sentencePlayback.sent.some(frame => frame.type === "session_hello"))).toBe(true);
});

test.afterEach(async ({ page }, info) => {
  if (info.status === info.expectedStatus) return;
  const evidence = await page.evaluate(() => ({ sent: window.__sentencePlayback.sent,
    sourceEvents: window.__sentencePlayback.sourceEvents, cleared: window.__sentencePlayback.cleared }));
  await info.attach("sentence-playback", { body: JSON.stringify(evidence), contentType: "application/json" });
});

const stop = { type: "assistant_speech_cancelled", output_epoch: "epoch", speech_id: "old",
  generation: 1, stop_command_id: "sentence-stop", sentence_permit: {
    permit_id: "permit", input_id: "input", input_version: 1, response_id: "old", reply_version: 1,
    sentence_id: "sentence", audio_start_samples: 0, audio_end_samples: 16000,
    sample_rate_hz: 16000, max_wait_ms: 1500,
  } };

test("real page retains one sentence and clears later PCM across a chunk boundary", async ({ page }) => {
  await page.evaluate(() => {
    const state = window.__sentencePlayback;
    state.inject({ type: "assistant_speech_text", generation: 1, text: "第一句。第二句。" });
    state.inject({ type: "assistant_text_alignment", generation: 1, output_epoch: "epoch", speech_id: "old",
      text: "第一句。", audio_start_us: 0, audio_end_us: 1000000, text_end_precision: "exact",
      sentence: { sentence_id: "sentence", text: "第一句。", text_start: 0, text_end: 4, audio_start_us: 0, audio_end_us: 1000000 } });
    for (let sequence = 0; sequence < 2; sequence++) state.inject({ type: "assistant_audio_chunk",
      generation: 1, speech_id: "old", sequence, sample_rate_hz: 16000,
      pcm16_base64: btoa("\0".repeat(64000)), is_final: sequence === 1 });
  });
  await expect.poll(() => page.evaluate(() => window.__sentencePlayback.sent.some(frame =>
    frame.type === "playback_progress_v2" && frame.speech_id === "old" && Number(frame.played_position_samples) > 1600)),
    { intervals: [30], timeout: 1000 }).toBe(true);
  await page.evaluate(frame => { window.__sentencePlayback.inject(frame); window.__sentencePlayback.inject(frame); }, stop);
  const results = () => page.evaluate(() => window.__sentencePlayback.sent.filter(frame => frame.type === "output_stop_result"));
  expect(await results()).toHaveLength(0);
  await expect.poll(results, { timeout: 2000 }).toHaveLength(2);
  const observed = await results();
  expect(observed[0]).toEqual(observed[1]);
  expect(observed[0]).toMatchObject({ outcome: "queue_stopped", played_position_samples: 16000 });
  const events = await page.evaluate(() => window.__sentencePlayback.sourceEvents);
  expect(events.filter(event => event.action === "stop" && Number(event.when) > Number(event.clock))).toHaveLength(1);
  expect(events.filter(event => event.action === "stop" && event.when === undefined)).toHaveLength(1);
  expect(await page.evaluate(() => window.__sentencePlayback.sent.some(frame =>
    frame.type === "playback_progress_v2" && frame.speech_id === "old" && frame.phase === "finished"))).toBe(false);
  await page.evaluate(() => {
    const state = window.__sentencePlayback;
    state.inject({ type: "assistant_audio_chunk", generation: 1, speech_id: "old", sequence: 2,
      sample_rate_hz: 16000, pcm16_base64: btoa("\0".repeat(64000)), is_final: true });
    state.inject({ type: "assistant_audio_chunk", generation: 2, speech_id: "new", sequence: 0,
      sample_rate_hz: 16000, pcm16_base64: btoa("\0".repeat(16000)), is_final: true });
  });
  await expect.poll(() => page.evaluate(() => window.__sentencePlayback.sent.some(frame =>
    frame.type === "playback_progress_v2" && frame.speech_id === "new")), { timeout: 1000 }).toBe(true);
  expect(await page.evaluate(() => window.__sentencePlayback.sourceEvents.filter(event => event.action === "start").length)).toBe(3);
});

test("old sentence permits do not clear the active replacement's playback timers", async ({ page }) => {
  await page.evaluate(() => {
    window.__sentencePlayback.inject({ type: "assistant_audio_chunk", generation: 2,
      speech_id: "new", sequence: 0, sample_rate_hz: 16000, pcm16_base64: btoa("\0".repeat(64000)), is_final: true });
    window.__sentencePlayback.inject({ type: "assistant_response_completed", generation: 2 });
  });
  await expect.poll(() => page.evaluate(() => window.__sentencePlayback.sent.some(frame =>
    frame.type === "playback_progress_v2" && frame.speech_id === "new"))).toBe(true);
  for (const frame of [stop, { ...stop, output_epoch: "expired", stop_command_id: "old-epoch" }]) {
    const cleared = await page.evaluate(value => {
      const state = window.__sentencePlayback;
      state.cleared = [];
      state.inject(value);
      return state.cleared;
    }, frame);
    expect(cleared).toEqual([]);
  }
});


for (const type of ["assistant_audio", "assistant_text", "assistant_speech_text", "assistant_response_completed"] as const) {
  test(`pending sentence stop rejects ${type} before changing speaking state`, async ({ page }) => {
    await page.evaluate(() => window.__sentencePlayback.inject({ type: "assistant_audio_chunk", generation: 1,
      speech_id: "old", sequence: 0, sample_rate_hz: 16000, pcm16_base64: btoa("\0".repeat(64000)), is_final: true }));
    await expect.poll(() => page.evaluate(() => window.__sentencePlayback.sent.some(frame =>
      frame.type === "playback_progress_v2" && Number(frame.played_position_samples) > 1600)),
      { intervals: [30], timeout: 1000 }).toBe(true);
    await page.evaluate(({ frame, type }) => {
      window.__sentencePlayback.inject(frame);
      window.__sentencePlayback.inject({ type, generation: 2, text: "替换回复。",
        sample_rate_hz: 16000, pcm16_base64: btoa("\0".repeat(16000)) });
    }, { frame: stop, type });
    await expect.poll(() => page.evaluate(() => window.__sentencePlayback.sent.filter(frame =>
      frame.type === "output_stop_result").length), { timeout: 2000 }).toBe(1);
    expect(await page.evaluate(() => window.__sentencePlayback.sourceEvents.filter(event => event.action === "start").length)).toBe(1);
    await expect(page.getByText("正在回答", { exact: true })).toHaveCount(0);
  });
}

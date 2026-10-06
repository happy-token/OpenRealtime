import { expect, test } from "@playwright/test";

test.afterEach(async ({ page }, info) => {
  if (info.status === info.expectedStatus) return;
  const evidence = await page.evaluate(() => {
    const state = (window as typeof window & { __playbackIsolation: {
      sent: Record<string, unknown>[]; contexts: AudioContext[]; sourceEvents: object[];
    } }).__playbackIsolation;
    return { sent: state.sent, sourceEvents: state.sourceEvents,
      clocks: state.contexts.map(context => ({ state: context.state, currentTime: context.currentTime })) };
  });
  await info.attach("playback-clock-evidence", { body: JSON.stringify(evidence, null, 2), contentType: "application/json" });
});

for (const scenario of [
  { generation: 1, preciseStop: true }, { generation: 2, preciseStop: true },
  { generation: 1, preciseStop: false }, { generation: 2, preciseStop: false },
]) {
const newGeneration = scenario.generation;
test(`late audio preserves generation ${newGeneration} replacement (${scenario.preciseStop ? "precise" : "legacy"} stop)`, async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("openrealtime-language", "zh-CN");
    type Listener = (event: Event | MessageEvent<string>) => void;
    const state = { sent: [] as Record<string, unknown>[], contexts: [] as AudioContext[], sourceEvents: [] as object[],
      inject: (frame: object) => { void frame; } };
    Object.assign(window, { __playbackIsolation: state });
    window.AudioContext = new Proxy(window.AudioContext, {
      construct(target, args) {
        const context = Reflect.construct(target, args) as AudioContext;
        state.contexts.push(context);
        const createSource = context.createBufferSource.bind(context);
        context.createBufferSource = () => {
          const source = createSource();
          const start = source.start.bind(source);
          const stop = source.stop.bind(source);
          source.start = when => {
            state.sourceEvents.push({ action: "start", when, duration: source.buffer?.duration, clock: context.currentTime });
            start(when);
          };
          source.stop = when => {
            state.sourceEvents.push({ action: "stop", when, clock: context.currentTime });
            stop(when);
          };
          source.addEventListener("ended", () => state.sourceEvents.push({ action: "ended", duration: source.buffer?.duration, clock: context.currentTime }));
          return source;
        };
        return context;
      },
    });
    class Socket {
      static CONNECTING = 0; static OPEN = 1; static CLOSING = 2; static CLOSED = 3;
      readyState = 0;
      listeners = new Map<string, Listener[]>();
      constructor() {
        state.inject = frame => this.message(frame);
        setTimeout(() => { this.readyState = 1; this.emit("open", new Event("open")); }, 0);
      }
      addEventListener(type: string, listener: Listener) {
        this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
      }
      emit(type: string, event: Event | MessageEvent<string>) {
        for (const listener of this.listeners.get(type) ?? []) listener(event);
      }
      message(frame: object) { this.emit("message", new MessageEvent("message", { data: JSON.stringify(frame) })); }
      send(raw: string) {
        const frame = JSON.parse(raw) as Record<string, unknown>;
        state.sent.push(frame);
        if (frame.type === "session_hello") {
          this.message({ type: "session_ack", session_id: "playback-e2e", resumed: false,
            protocol_version: 2, resume_token: "token", output_epoch: "server-output" });
          this.message({ type: "session_capabilities", server_asr: false, server_tts: true,
            assistant_text_streaming: true, user_transcript_streaming: false });
        }
      }
      close() { this.readyState = 3; this.emit("close", new Event("close")); }
    }
    const NativeSocket = window.WebSocket;
    window.WebSocket = new Proxy(NativeSocket, {
      construct(target, args) {
        const url = new URL(String(args[0]), location.href);
        return url.port === "8765" || url.pathname === "/voice" ? new Socket() : Reflect.construct(target, args);
      },
    });
    class Recognition {
      continuous = true; interimResults = true; lang = "zh-CN";
      start() {} stop() {} abort() {}
    }
    Object.assign(window, { SpeechRecognition: Recognition, webkitSpeechRecognition: Recognition });
  });
  await page.goto("/conversation?role_id=e2e-unassigned");
  await page.getByRole("button", { name: "主页开始对话" }).click();
  await expect(page.getByRole("button", { name: "关闭麦克风" })).toBeVisible();
  await expect.poll(() => page.evaluate(() => {
    const state = (window as typeof window & { __playbackIsolation: { sent: Record<string, unknown>[] } }).__playbackIsolation;
    return state.sent.some(frame => frame.type === "session_hello");
  })).toBe(true);
  await page.evaluate(({ generation, preciseStop }) => {
    const state = (window as typeof window & { __playbackIsolation: { inject: (frame: object) => void } }).__playbackIsolation;
    state.inject({ type: "assistant_audio_chunk", generation: 1, speech_id: "old", sequence: 0,
      sample_rate_hz: 16000, pcm16_base64: btoa("\0".repeat(64000)), is_final: true });
    const stop = { type: "assistant_speech_cancelled", generation: 1,
      output_epoch: "server-output", speech_id: "old", stop_command_id: "stop-old" };
    if (preciseStop) state.inject(stop);
    state.inject({ type: "assistant_audio_chunk", generation, speech_id: "new", sequence: 0,
      sample_rate_hz: 16000, pcm16_base64: btoa("\0".repeat(25600)), is_final: true });
    state.inject({ type: "assistant_audio_chunk", generation: 1, speech_id: "old", sequence: 1,
      sample_rate_hz: 16000, pcm16_base64: btoa("\0".repeat(64000)), is_final: true });
    if (preciseStop) {
      state.inject(stop);
      state.inject({ ...stop, output_epoch: "expired", stop_command_id: "expired-stop" });
    } else if (generation > 1) state.inject({ type: "assistant_speech_cancelled", generation: 1 });
  }, scenario);
  const frames = () => page.evaluate(() => (window as typeof window & {
    __playbackIsolation: { sent: Record<string, unknown>[] }
  }).__playbackIsolation.sent.filter(frame => frame.type === "playback_progress_v2"));
  await expect.poll(() => page.evaluate(() => {
    const state = (window as typeof window & { __playbackIsolation: {
      sent: Record<string, unknown>[]; contexts: AudioContext[];
    } }).__playbackIsolation;
    return { progress: state.sent.filter(frame => frame.type === "playback_progress_v2")
      .map(frame => ({ speech_id: frame.speech_id, generation: frame.generation, phase: frame.phase })),
      clocks: state.contexts.map(context => ({ state: context.state, currentTime: context.currentTime })) };
  }), { timeout: 3000 }).toMatchObject({ progress: expect.arrayContaining([
    { speech_id: "new", generation: newGeneration, phase: "finished" },
  ]) });
  const observed = await frames();
  expect(observed.every(frame => frame.output_epoch === "server-output")).toBe(true);
  expect(observed.some(frame => frame.speech_id === "old" && frame.phase === "finished")).toBe(false);
  if (scenario.preciseStop) {
    const results = await page.evaluate(() => (window as typeof window & {
      __playbackIsolation: { sent: Record<string, unknown>[] }
    }).__playbackIsolation.sent.filter(frame => frame.type === "output_stop_result"));
    expect(results).toHaveLength(3);
    expect(results[0]).toEqual(results[1]);
    expect(results[0]).toMatchObject({ stop_command_id: "stop-old", output_epoch: "server-output",
      speech_id: "old", outcome: "queue_stopped" });
    expect(results[2]).toMatchObject({ output_epoch: "expired", outcome: "stale" });
  } else if (newGeneration > 1) expect(observed.some(frame => frame.speech_id === "old" && frame.phase === "stopped")).toBe(true);
});
}

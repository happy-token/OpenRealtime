import { expect, test } from "@playwright/test";

test("input failure closes capture and browser speech while preserving conversation text", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("openrealtime-language", "zh-CN");
    type Listener = (event: Event | MessageEvent<string>) => void;
    const state = { aborts: 0, spoken: [] as string[], cancels: 0, failure: () => {} };
    Object.assign(window, { __inputFailureTest: state });
    class Socket {
      static CONNECTING = 0;
      static OPEN = 1;
      static CLOSING = 2;
      static CLOSED = 3;
      CONNECTING = 0;
      OPEN = 1;
      CLOSING = 2;
      CLOSED = 3;
      readyState = 0;
      listeners = new Map<string, Listener[]>();
      constructor() {
        state.failure = () => this.message({ type: "voice_session_failed", error_id: "failure",
          code: "semantic_input_rejected", phase: "input", retryable: true,
          session_disposition: "close", safe_message: "输入证据未确认保存，请重新开始会话。" });
        setTimeout(() => { this.readyState = 1; this.emit("open", new Event("open")); }, 0);
      }
      addEventListener(type: string, listener: Listener) {
        this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
      }
      emit(type: string, event: Event | MessageEvent<string>) {
        for (const listener of this.listeners.get(type) ?? []) listener(event);
      }
      message(frame: object) {
        this.emit("message", new MessageEvent("message", { data: JSON.stringify(frame) }));
      }
      send(raw: string) {
        const frame = JSON.parse(raw) as { type: string };
        if (frame.type === "session_hello") {
          this.message({ type: "session_ack", session_id: "e2e", resumed: false });
          this.message({ type: "session_capabilities", server_asr: false, server_tts: false,
            assistant_text_streaming: true, user_transcript_streaming: false });
        }
        if (frame.type === "user_text") {
          setTimeout(() => {
            this.message({ type: "assistant_text", generation: 1, text: "这是已经显示的回答。" });
            this.message({ type: "assistant_response_completed", generation: 1 });
          }, 50);
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
      continuous = true;
      interimResults = true;
      lang = "zh-CN";
      onresult: ((event: object) => void) | null = null;
      onerror: ((event: object) => void) | null = null;
      onend: (() => void) | null = null;
      start() { setTimeout(() => this.onresult?.({ resultIndex: 0,
        results: [Object.assign([{ transcript: "这是用户的问题" }], { isFinal: true })] }), 100); }
      stop() { state.aborts += 1; }
      abort() { state.aborts += 1; }
    }
    Object.assign(window, { SpeechRecognition: Recognition, webkitSpeechRecognition: Recognition });
    window.speechSynthesis.speak = utterance => { state.spoken.push(utterance.text); };
    window.speechSynthesis.cancel = () => { state.cancels += 1; };
  });
  await page.goto("/conversation?role_id=e2e-unassigned");
  await expect(page.getByRole("button", { name: "主页开始对话" })).toBeEnabled();
  await page.getByRole("button", { name: "主页开始对话" }).click();
  const state = () => page.evaluate(() => {
    const value = (window as typeof window & { __inputFailureTest: { aborts: number; spoken: string[]; cancels: number } }).__inputFailureTest;
    return { aborts: value.aborts, spoken: value.spoken, cancels: value.cancels };
  });
  await expect.poll(async () => (await state()).spoken).toEqual(["这是已经显示的回答。"]);
  const before = await state();
  await page.evaluate(() => (window as typeof window & { __inputFailureTest: { failure: () => void } }).__inputFailureTest.failure());
  await expect.poll(async () => (await state()).aborts).toBeGreaterThan(before.aborts);
  await expect.poll(async () => (await state()).cancels).toBeGreaterThan(before.cancels);
  await expect(page.getByText("输入证据未确认保存，请重新开始会话。", { exact: true }).first()).toBeVisible();
  await expect(page.locator(".current-turn-text")).toContainText("这是已经显示的回答。");
  await expect(page.getByRole("button", { name: "关闭麦克风" })).toHaveCount(0);
});

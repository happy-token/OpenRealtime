import { test, expect } from "@playwright/test";

test("text chat needs no microphone and retains an offline draft until retry succeeds", async ({ page }) => {
  await page.addInitScript(() => {
    type Listener = (event: Event) => void;
    const sockets: Socket[] = [];
    class Socket {
      static OPEN = 1;
      static CLOSED = 3;
      readyState = 0;
      listeners = new Map<string, Listener[]>();
      constructor() {
        sockets.push(this);
        Object.assign(window, { connectTextTestSocket: () => {
          for (const socket of sockets) {
            if (socket.readyState !== 0) continue;
            socket.readyState = 1;
            socket.emit("open", new Event("open"));
          }
        } });
      }
      addEventListener(type: string, listener: Listener) {
        this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
      }
      emit(type: string, event: Event) {
        this.listeners.get(type)?.forEach((listener) => listener(event));
      }
      message(frame: object) {
        this.emit("message", new MessageEvent("message", { data: JSON.stringify(frame) }));
      }
      send(raw: string) {
        const frame = JSON.parse(raw);
        if (frame.type === "session_hello") {
          this.message({ type: "session_ack", session_id: "text-test", resumed: false });
          this.message({ type: "session_capabilities", server_asr: false, server_tts: false,
            assistant_text_streaming: true, user_transcript_streaming: false });
        }
        if (frame.type === "user_text") {
          setTimeout(() => {
            this.message({ type: "assistant_text", text: `收到：${frame.text}`, generation: 1 });
            this.message({ type: "assistant_response_completed", generation: 1 });
          }, 20);
        }
      }
      close() { this.readyState = 3; }
    }
    Object.assign(window, { WebSocket: Socket, SpeechRecognition: undefined, webkitSpeechRecognition: undefined });
    Object.defineProperty(navigator.mediaDevices, "getUserMedia", { value: () => {
      throw new Error("Text chat must not request microphone access");
    } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "使用文字对话" }).click();
  const input = page.getByRole("textbox", { name: "输入对话消息" });
  await input.fill("你好，文字模式");
  await page.getByRole("button", { name: "发送消息" }).click();
  await expect(input).toHaveValue("你好，文字模式");
  await expect(page.locator(".session-chat-input").getByRole("alert")).toContainText("草稿已保留");
  await page.evaluate(() => (window as unknown as { connectTextTestSocket: () => void }).connectTextTestSocket());
  await expect(page.locator(".offline-hint")).toHaveAttribute("data-offline", "false");
  await page.getByRole("button", { name: "发送消息" }).click();
  await expect(input).toHaveValue("");
  await expect(page.locator(".session-chat-input").getByRole("alert")).toHaveCount(0);
  await expect(page.locator(".bubble--assistant")).toContainText("收到：你好，文字模式");
});

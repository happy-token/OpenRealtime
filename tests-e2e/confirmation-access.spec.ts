import { test, expect } from "@playwright/test";

test("confirmation traps keyboard focus, rejects on Escape and restores focus", async ({ page }) => {
  await page.addInitScript(() => {
    class Socket {
      static OPEN = 1;
      readyState = 0;
      listeners = new Map<string, ((event: Event) => void)[]>();
      constructor() { setTimeout(() => { this.readyState = 1; this.emit("open", new Event("open")); }, 0); }
      addEventListener(type: string, listener: (event: Event) => void) {
        this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
      }
      emit(type: string, event: Event) { this.listeners.get(type)?.forEach((listener) => listener(event)); }
      message(frame: object) { this.emit("message", new MessageEvent("message", { data: JSON.stringify(frame) })); }
      send(raw: string) {
        const frame = JSON.parse(raw);
        if (frame.type === "session_hello") {
          this.message({ type: "session_ack", session_id: "confirm-test", resumed: false });
          this.message({ type: "session_capabilities", server_asr: false, server_tts: false });
          Object.assign(window, { requestTestConfirmation: (channel: string) => this.message({
            type: "confirmation_requested", confirmation_id: "confirmation-1", action_digest: "a".repeat(64),
            summary: "发送测试消息", required_channel: channel,
            expires_at: new Date(Date.now() + 60_000).toISOString(), generation: 1,
          }) });
        }
        if (frame.type === "confirmation_decision") {
          Object.assign(window, { testDecision: frame.approved });
          this.message({ type: "confirmation_resolution", confirmation_id: "confirmation-1",
            applied: true, approved: frame.approved, success: true, message: "操作已处理" });
        }
      }
      close() { this.readyState = 3; }
    }
    class Recognition { start() {} stop() {} abort() {} }
    Object.assign(window, { WebSocket: Socket, SpeechRecognition: Recognition });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "主页开始对话" }).click();
  await page.getByRole("button", { name: "展开文字输入" }).click();
  const input = page.getByRole("textbox", { name: "输入对话消息" });
  await input.focus();
  await page.evaluate(() => (window as unknown as { requestTestConfirmation: (channel: string) => void }).requestTestConfirmation("voice"));
  const dialog = page.getByRole("alertdialog");
  const reject = dialog.getByRole("button", { name: "拒绝" });
  await expect(reject).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(dialog.getByRole("button", { name: "确认执行" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(reject).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(input).toBeFocused();
  expect(await page.evaluate(() => (window as unknown as { testDecision: boolean }).testDecision)).toBe(false);
  await page.evaluate(() => (window as unknown as { requestTestConfirmation: (channel: string) => void }).requestTestConfirmation("strong"));
  await expect(dialog.getByRole("button", { name: "确认执行" })).toBeDisabled();
  await page.keyboard.press("Tab");
  await expect(reject).toBeFocused();
});

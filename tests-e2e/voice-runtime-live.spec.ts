import { expect, test } from "@playwright/test";
import { appendFileSync } from "node:fs";

for (const stopDuringPlayback of [false, true]) {
  test(stopDuringPlayback
    ? "Chrome real voice call stops active browser audio on hangup"
    : "Chrome file-backed microphone completes a real Cascaded voice turn", async ({ page }, testInfo) => {
    test.skip(
      !process.env.VOICEAGENT_E2E_FULL_VOICE,
      "requires the real Voice Runtime and a configured microphone WAV",
    );
    test.setTimeout(90_000);
    await page.addInitScript(() => {
      localStorage.setItem("openrealtime-language", "zh-CN");
      const active = new Set<AudioBufferSourceNode>();
      let starts = 0;
      const originalStart = AudioBufferSourceNode.prototype.start;
      const originalStop = AudioBufferSourceNode.prototype.stop;
      AudioBufferSourceNode.prototype.start = function (...args: Parameters<typeof originalStart>) {
        const result = originalStart.apply(this, args);
        starts += 1;
        active.add(this);
        this.addEventListener("ended", () => active.delete(this), { once: true });
        return result;
      };
      AudioBufferSourceNode.prototype.stop = function (...args: Parameters<typeof originalStop>) {
        const result = originalStop.apply(this, args);
        active.delete(this);
        return result;
      };
      Object.defineProperty(window, "__e2ePlayback", {
        value: () => ({ starts, active: active.size }),
      });
    });
    const receivedTypes: string[] = [];
    const sessionIds: string[] = [];
    page.on("websocket", socket => socket.on("framereceived", ({ payload }) => {
      if (typeof payload !== "string") return;
      try {
        const frame = JSON.parse(payload);
        if (typeof frame.type === "string") receivedTypes.push(frame.type);
        if (frame.type === "session_ack" && typeof frame.session_id === "string") sessionIds.push(frame.session_id);
      } catch { /* Binary audio has no JSON metadata. */ }
    }));

    const sessionId = new Promise<string>((resolve) => {
      let recorded = false;
      page.on("websocket", (socket) => {
        socket.on("framereceived", ({ payload }) => {
          if (recorded) return;
          if (typeof payload !== "string") return;
          try {
            const frame = JSON.parse(payload) as { type?: unknown; session_id?: unknown };
            if (frame.type === "session_ack" && typeof frame.session_id === "string") {
              recorded = true;
              if (process.env.VOICEAGENT_E2E_SESSION_LOG) {
                appendFileSync(
                  process.env.VOICEAGENT_E2E_SESSION_LOG,
                  `${frame.session_id}\n`,
                  "utf8",
                );
              }
              resolve(frame.session_id);
            }
          } catch {
            // Binary audio and non-JSON provider frames are irrelevant here.
          }
        });
      });
    });

    await page.goto("/");
    await page.getByRole("button", { name: "主页开始对话", exact: true }).click();
    await page.getByRole("button", { name: /^页面形态：/ }).hover();
    await page.getByRole("menuitemradio", { name: /内容/ }).click();

    const userTurns = page.locator(".bubble--user");
    await expect(userTurns.first()).toContainText(
      process.env.VOICEAGENT_E2E_EXPECTED_TRANSCRIPT ?? "你好",
      { timeout: 30_000 },
    );

    if (stopDuringPlayback) {
      await expect.poll(() => page.evaluate(() => {
        const read = (window as typeof window & { __e2ePlayback: () => { starts: number; active: number } }).__e2ePlayback;
        return read().active;
      }), { timeout: 30_000 }).toBeGreaterThan(0);
      await page.getByRole("button", { name: "结束通话" }).click();
      await expect(page.locator(".status-dot")).toHaveAttribute("data-state", "idle");
      await expect.poll(() => page.evaluate(() =>
        (window as typeof window & { __e2ePlayback: () => { active: number } }).__e2ePlayback().active,
      )).toBe(0);
      await testInfo.attach("voice-wire-evidence", { body: JSON.stringify({ sessionIds, receivedTypes }), contentType: "application/json" });
      return;
    }

    const completedAssistantTurn = page
      .locator('.bubble--assistant[data-status="completed"]')
      .last();
    await expect(completedAssistantTurn).toBeVisible({ timeout: 30_000 });
    await expect(completedAssistantTurn).toContainText(/\S/);
    await expect(page.locator(".status-dot")).toHaveAttribute(
      "data-state",
      "listening",
      { timeout: 30_000 },
    );

    await sessionId;
    expect(await page.evaluate(() =>
      (window as typeof window & { __e2ePlayback: () => { starts: number } }).__e2ePlayback().starts,
    )).toBeGreaterThan(0);

    await page.getByRole("button", { name: "结束通话" }).click();
    await testInfo.attach("voice-wire-evidence", { body: JSON.stringify({ sessionIds, receivedTypes }), contentType: "application/json" });
  });
}

import { expect, test } from "@playwright/test";
import { appendFileSync } from "node:fs";

test("Chrome file-backed microphone completes a real Cascaded voice turn", async ({ page }) => {
  test.skip(
    !process.env.VOICEAGENT_E2E_FULL_VOICE,
    "requires the real Voice Runtime and a configured microphone WAV",
  );
  test.setTimeout(60_000);

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
  await page.getByRole("button", { name: "开始语音对话" }).click();
  await page.getByRole("button", { name: /^页面形态：/ }).click();
  await page.getByRole("menuitemradio", { name: /内容/ }).click();

  const userTurns = page.locator(".bubble--user");
  await expect(userTurns.first()).toContainText(
    process.env.VOICEAGENT_E2E_EXPECTED_TRANSCRIPT ?? "你好",
    { timeout: 30_000 },
  );

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

  await page.getByRole("button", { name: "结束通话" }).click();
});

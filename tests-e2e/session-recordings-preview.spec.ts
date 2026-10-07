import { test, expect } from "@playwright/test";

test("recording entry follows diagnostic theme without reading private audio in preview", async ({ page }) => {
  const recordingRequests: string[] = [];
  page.on("request", request => { if (request.url().includes("/recordings")) recordingRequests.push(request.url()); });
  await page.goto("/demos/diagnostics");
  await page.locator('a[href*="/demos/diagnostics?session="]').first().click();
  const panel = page.getByRole("region", { name: "会话录音" });
  await expect(panel.getByRole("heading", { name: "会话录音" })).toBeVisible();
  await expect(panel.getByRole("button", { name: "查看录音" })).toBeDisabled();
  await expect(panel).toContainText("预览页面不读取真实录音");
  await expect(panel).toContainText("已发送不代表已播放");
  expect(recordingRequests).toEqual([]);
  expect(await panel.locator("audio").count()).toBe(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(panel.getByRole("button", { name: "查看录音" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

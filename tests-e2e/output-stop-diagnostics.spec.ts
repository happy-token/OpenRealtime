import { test, expect } from "@playwright/test";

test("precise stop diagnostics keep numeric stages and inspectable target identity", async ({ page }) => {
  await page.goto("/demos/diagnostics?session=preview-voice-1");
  await page.getByRole("button", { name: /轮次 3 ·/ }).click();
  await page.getByRole("tab", { name: "打断过程" }).click();
  const panel = page.getByRole("tabpanel");
  for (const [label, value] of [["停播回执延迟", "100ms"], ["停播投影等待", "40ms"], ["停播交接总等待", "140ms"]]) {
    const metric = panel.locator("div[title]").filter({ hasText: label });
    await expect(metric).toContainText(value);
    await expect(metric).toHaveAttribute("title", /仅统计|不应重复相加/);
  }
  await expect(panel).toContainText("停播回执仅证明本地音频队列已停止");
  const receipt = panel.locator("div").filter({ has: page.locator("strong", { hasText: /^收到停播回执$/ }) }).last();
  await receipt.locator("summary").click();
  await expect(receipt.locator("pre")).toContainText('"stop_command_id": "preview-voice-1-stop-1"');
  await expect(receipt.locator("pre")).toContainText('"played_position_samples": 1200');
  await expect(receipt.locator("pre")).toContainText('"generation": 3');
});

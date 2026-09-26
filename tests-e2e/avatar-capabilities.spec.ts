import { test, expect } from "@playwright/test";

test("shows missing avatar access before starting without an extra homepage text button", async ({ page }) => {
  await page.route("**/api/avatar-capabilities", (route) => route.fulfill({ json: Object.fromEntries(
    ["assets", "anam", "heygen", "localRenderer"].map((key) => [key, {
      state: "login_required", message: "请先登录管理员账号，再使用此能力。",
    }]),
  ) }));
  await page.addInitScript(() => localStorage.setItem("voice-agent-experience-mode", "avatar"));
  await page.goto("/");
  await expect(page.getByText("请先登录管理员账号，再使用此能力。")).toBeVisible();
  await expect(page.getByRole("link", { name: "管理员登录" })).toBeVisible();
  await expect(page.getByRole("button", { name: "使用文字对话" })).toHaveCount(0);
});

test("capability fetch failures are actionable and recover on retry", async ({ page }) => {
  let fail = true;
  await page.route("**/api/avatar-capabilities", (route) => fail
    ? route.fulfill({ status: 503, json: { error: "offline" } })
    : route.fulfill({ json: Object.fromEntries(["assets", "anam", "heygen", "localRenderer"].map((key) => [key, {
      state: "available", message: "配置已就绪，启动时会检查服务连接。",
    }])) }));
  await page.addInitScript(() => localStorage.setItem("voice-agent-experience-mode", "avatar"));
  await page.goto("/");
  await expect(page.getByText("能力信息暂时不可用，请重试。")).toBeVisible();
  fail = false;
  await page.getByRole("button", { name: "重新检查" }).click();
  await expect(page.locator(".avatar-capability-notice")).toHaveCount(0);
});

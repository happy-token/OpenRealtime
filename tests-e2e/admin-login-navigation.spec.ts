import { expect, test } from "@playwright/test";

test("expired account reaches SSO through document navigation without an RSC fetch error", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("openrealtime-language", "zh-CN"));
  const errors: string[] = [];
  const loginRequests: boolean[] = [];
  page.on("console", message => {
    if (message.type() === "error") errors.push(message.text());
  });
  await page.route("**/api/user/login?next=%2Fsettings%2Fsession-diagnostics", route => {
    loginRequests.push(route.request().isNavigationRequest());
    return route.fulfill({ status: 302, headers: { location: "https://identity.example.test/authorize" } });
  });
  await page.route("https://identity.example.test/authorize", route => route.fulfill({
    contentType: "text/html; charset=utf-8", body: "<h1>SSO 登录</h1>",
  }));
  await page.goto("/settings");
  await page.getByRole("button", { name: "固定展开侧边栏", exact: true }).click();
  await page.getByRole("link", { name: "会话诊断", exact: true }).click();
  await expect(page).toHaveURL("https://identity.example.test/authorize");
  await expect(page.getByRole("heading", { name: "SSO 登录" })).toBeVisible();
  expect(loginRequests.length).toBeGreaterThan(0);
  expect(loginRequests.every(Boolean)).toBe(true);
  expect(errors.filter(error => /Failed to fetch|RSC payload/i.test(error))).toEqual([]);
});

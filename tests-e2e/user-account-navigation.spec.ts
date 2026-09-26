import { expect, test } from "@playwright/test";

test("signed-out users can start login from navigation and profile", async ({ page }) => {
  await page.route("**/api/user/me", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ signedIn: false }),
  }));

  await page.goto("/roles");
  await page.getByRole("button", { name: "固定展开侧边栏" }).click();
  await expect(page.getByRole("link", { name: /登录/ })).toHaveAttribute(
    "href",
    "/api/user/login?next=%2Froles",
  );

  await page.goto("/settings/profile");
  await expect(page.getByRole("link", { name: "登录账户" })).toHaveAttribute(
    "href",
    "/api/user/login?next=%2Fsettings%2Fprofile",
  );
});

test("signed-in users see their identity and can log out with POST", async ({ page }) => {
  await page.route("**/api/user/me", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      signedIn: true,
      user: { issuer: "https://login.example", subject: "alice" },
    }),
  }));
  let logoutMethod = "";
  await page.route("**/api/user/logout", (route) => {
    logoutMethod = route.request().method();
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) });
  });

  await page.goto("/settings/profile");
  await expect(page.getByText("alice", { exact: true })).toBeVisible();
  await expect(page.getByText("login.example", { exact: true })).toBeVisible();

  await page.goto("/roles");
  await page.getByRole("button", { name: "固定展开侧边栏" }).click();
  await page.getByRole("button", { name: /alice/ }).click();
  await page.getByRole("button", { name: "退出登录" }).click();

  await expect.poll(() => logoutMethod).toBe("POST");
  await expect(page).toHaveURL(/\/(?:conversation)?$/);
});

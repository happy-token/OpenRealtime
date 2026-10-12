import { expect, test } from "@playwright/test";

test("documentation leads with voice experience and retains the document Q&A walkthrough", async ({ page }, testInfo) => {
  await page.addInitScript(() => localStorage.setItem("openrealtime-language", "zh-CN"));
  await page.goto("/docs");
  const reader = page.locator('[aria-label="文档阅读区域"]');
  await expect(page.getByRole("heading", { name: "用语音聊天和工作", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "智能判停，给思考留时间", exact: true })).toBeVisible();
  await expect(page.getByText("准备产品资料", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "认识产品与开始使用", exact: true })).toBeVisible();
  await expect(reader.locator("details")).not.toHaveAttribute("open", "");
  await page.screenshot({ path: testInfo.outputPath("docs-desktop.png") });
  await page.getByRole("link", { name: "体验实时语音", exact: true }).click();
  await expect(page).toHaveURL(/\/conversation\?role_mode=conversation&experience=voice$/);
  await page.goto("/docs");
  await page.getByRole("link", { name: /用产品资料配置语音助手/ }).click();
  await expect(page).toHaveURL(/\/docs\/product-assistant$/);
  await expect(page.locator("article")).toHaveAttribute("lang", "zh-CN");
  await expect(page.locator("article")).toContainText("星河产品说明 v1");
  await expect(page.locator("article")).toContainText("资料未说明");
  const roleLink = page.locator('article a[href="/docs/role-configuration"]');
  await roleLink.click();
  await expect(page).toHaveURL(/\/docs\/role-configuration$/);
  await expect(page.locator("article")).toContainText("完整示例");
});

test("English introduction has English prose while untranslated guides identify their language", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("openrealtime-language", "en"));
  await page.goto("/docs");
  await expect(page.getByRole("heading", { name: "Chat and work through voice", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Try real-time voice", exact: true })).toBeVisible();
  await page.goto("/docs/overview");
  await expect(page.locator("article")).toHaveAttribute("lang", "en");
  await expect(page.locator("article")).toContainText("product documentation");
  await page.locator('article a[href="/docs/product-assistant"]').first().click();
  await expect(page.locator("article")).toContainText("Starflow product guide v1");
  await expect(page.locator("article")).toHaveAttribute("lang", "en");
  await page.locator('article a[href="/docs/knowledge-base"]').first().click();
  await expect(page.locator("article")).toHaveAttribute("lang", "zh-CN");
  await expect(page.getByText("Article language: Chinese", { exact: false })).toBeVisible();
  await page.goto("/docs/chat-agent-integration");
  await expect(page.locator("article")).toHaveAttribute("lang", "en");
  await expect(page.locator("article")).toContainText("Keep your conversational capabilities");
  await page.goto("/docs/cost-and-flexibility");
  await expect(page.locator("article")).toHaveAttribute("lang", "en");
  await expect(page.locator("article")).toContainText("Compare total costs");
});

test("mobile documentation scrolls, expands research and preserves an existing article route", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => localStorage.setItem("openrealtime-language", "zh-CN"));
  await page.goto("/docs");
  await expect(page.getByRole("link", { name: "体验实时语音", exact: true })).toBeVisible();
  const menu = await page.getByRole("button", { name: "打开导航", exact: true }).boundingBox();
  const introduction = await page.getByText("OpenRealtime 文档", { exact: true }).boundingBox();
  expect(introduction?.y).toBeGreaterThanOrEqual((menu?.y ?? 0) + (menu?.height ?? 0));
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("docs-mobile.png") });
  await page.getByText("研究与规划", { exact: true }).click();
  await page.getByRole("link", { name: /项目完善清单/ }).click();
  await expect(page).toHaveURL(/\/docs\/project-improvements$/);
  await expect(page.locator("article")).toBeVisible();
  await page.locator("summary").click();
  const oldGuide = page.getByRole("link", { name: "首页使用指南", exact: true });
  await oldGuide.scrollIntoViewIfNeeded();
  await oldGuide.click();
  await expect(page).toHaveURL(/\/docs\/quick-start$/);
  await expect(page.locator("article")).toContainText("用自己的产品资料回答问题");
});

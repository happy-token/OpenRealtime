import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/demos/call-controls-demo.html");
});

test("sidecar and content retain the same persistent inline input and button positions", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const positions = await Promise.all(["#mic", "#mode", "#end"].map(selector =>
    page.locator(selector).boundingBox(),
  ));
  const initialDock = await page.locator("#dock").boundingBox();
  for (const name of ["内容", "并排"]) {
    await page.getByRole("navigation", { name: "页面模式" }).getByRole("button", { name, exact: true }).click();
    for (const [index, selector] of ["#mic", "#mode", "#end"].entries()) {
      const box = await page.locator(selector).boundingBox();
      expect(box).not.toBeNull();
      expect(box!.x).toBeCloseTo(positions[index]!.x, 0);
      expect(box!.y).toBeCloseTo(positions[index]!.y, 0);
    }
    await expect(page.locator("#captions")).toBeHidden();
    await expect(page.getByRole("textbox", { name: "输入对话消息" })).toBeVisible();
    await expect(page.locator("#input-toggle")).toBeHidden();
    expect(await page.locator("#dock").boundingBox()).toEqual(initialDock);
  }
  expect(errors).toEqual([]);
});

test("fullscreen toggles twice, preserves draft into content, and restores all call actions", async ({ page }) => {
  await page.getByRole("navigation", { name: "页面模式" }).getByRole("button", { name: "全屏", exact: true }).click();
  await page.getByRole("button", { name: "展开文字输入" }).click();
  await expect(page.locator("#dock")).toHaveAttribute("data-expanded", "true");
  const input = page.getByRole("textbox", { name: "输入对话消息" });
  await expect(input).toBeFocused();
  await input.fill("保留这条未发送的补充");
  await expect(page.locator("#main-actions")).toHaveJSProperty("inert", true);
  await expect(page.getByRole("button", { name: "结束预览", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "展开通话操作" })).toBeVisible();
  await page.getByRole("button", { name: "收起文字输入" }).click();
  await expect(input).toBeHidden();
  await expect(page.getByRole("button", { name: "关闭麦克风", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "展开文字输入" }).click();
  await expect(input).toHaveValue("保留这条未发送的补充");
  await input.press("Escape");
  await expect(page.getByRole("button", { name: "展开文字输入" })).toBeFocused();
  await page.getByRole("navigation", { name: "页面模式" }).getByRole("button", { name: "内容", exact: true }).click();
  await expect(input).toHaveValue("保留这条未发送的补充");
  await expect(input).toBeVisible();
});

test("expanded input keeps microphone and layout accessible through more actions", async ({ page }) => {
  await page.getByRole("navigation", { name: "页面模式" }).getByRole("button", { name: "全屏", exact: true }).click();
  await page.getByRole("button", { name: "展开文字输入" }).click();
  await page.getByRole("button", { name: "展开通话操作", exact: true }).click();
  const panel = page.getByRole("region", { name: "更多通话操作面板" });
  await expect(panel).toBeVisible();
  await panel.getByRole("button", { name: "关闭麦克风", exact: true }).click();
  await expect(page.locator("#stage")).toHaveAttribute("data-muted", "true");
  await panel.getByRole("radio", { name: "全屏" }).click();
  await expect(panel).toBeHidden();
  await expect(page.locator("#dock")).toHaveAttribute("data-expanded", "true");
  await page.getByRole("button", { name: "展开通话操作", exact: true }).click();
  await panel.getByRole("button", { name: "隐藏字幕" }).click();
  await expect(page.locator("#caption")).toBeHidden();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "展开通话操作", exact: true })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "开启麦克风", exact: true })).toBeVisible();
});

test("sending collapses the input and treats text as text", async ({ page }) => {
  await page.getByRole("navigation", { name: "页面模式" }).getByRole("button", { name: "全屏", exact: true }).click();
  await page.getByRole("button", { name: "展开文字输入" }).click();
  const input = page.getByRole("textbox", { name: "输入对话消息" });
  await input.fill('<img src=x onerror="alert(1)">');
  await input.press("Shift+Enter");
  await expect(page.locator("#dock")).toHaveAttribute("data-expanded", "true");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.locator("#messages")).toContainText('<img src=x onerror="alert(1)">');
  await expect(page.locator("#messages img")).toHaveCount(0);
  await expect(page.locator("#dock")).toHaveAttribute("data-expanded", "false");
  await page.getByRole("button", { name: "展开文字输入" }).click();
  await expect(input).toBeEmpty();
  await expect(page.getByRole("button", { name: "发送", exact: true })).toBeDisabled();
});

test("ending the preview works during input and can be restarted", async ({ page }) => {
  await page.getByRole("navigation", { name: "页面模式" }).getByRole("button", { name: "全屏", exact: true }).click();
  await page.getByRole("button", { name: "展开文字输入" }).click();
  await page.getByRole("textbox", { name: "输入对话消息" }).fill("草稿");
  await page.getByRole("button", { name: "展开通话操作" }).click();
  await page.locator("#menu-end").click();
  await expect(page.getByRole("dialog", { name: "预览已结束" })).toBeVisible();
  await expect(page.locator("#dock")).toHaveJSProperty("inert", true);
  await expect(page.locator(".topbar")).toHaveJSProperty("inert", true);
  await expect(page.locator(".footnote")).toHaveJSProperty("inert", true);
  await page.locator("#theme").evaluate(element => (element as HTMLSelectElement).focus());
  await expect(page.getByRole("button", { name: "重新体验" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "重新体验" })).toBeFocused();
  await page.getByRole("button", { name: "重新体验" }).click();
  await expect(page.locator(".topbar")).toHaveJSProperty("inert", false);
  await expect(page.locator(".footnote")).toHaveJSProperty("inert", false);
  await page.getByRole("button", { name: "展开文字输入" }).click();
  await expect(page.getByRole("textbox", { name: "输入对话消息" })).toHaveValue("草稿");
});

test("mobile input remains inside the screen and respects reduced motion", async ({ page }) => {
  await page.getByRole("navigation", { name: "页面模式" }).getByRole("button", { name: "全屏", exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.getByRole("button", { name: "展开文字输入" }).click();
  const box = await page.locator("#dock").boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(390);
  await expect(page.getByRole("button", { name: "展开通话操作" })).toBeVisible();
  await expect(page.getByRole("button", { name: "收起文字输入" })).toBeVisible();
  expect(await page.locator("#dock").evaluate(element => getComputedStyle(element).transitionDuration)).toBe("0s");
  await page.screenshot({ path: "test-results/call-controls-mobile-expanded.png" });
});

test("theme preview matches project tokens without overwriting account preferences", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("openrealtime-app-theme", "nord"));
  await page.reload();
  await expect(page.locator("body")).toHaveAttribute("data-theme", "nord");
  await page.getByRole("combobox", { name: "演示主题" }).selectOption("tokyo-night");
  await expect(page.locator("body")).toHaveAttribute("data-theme", "tokyo-night");
  expect(await page.evaluate(() => localStorage.getItem("openrealtime-app-theme"))).toBe("nord");
  await page.getByRole("textbox", { name: "输入对话消息" }).fill("我想再补充一句…");
  await page.waitForTimeout(500);
  await page.screenshot({ path: "test-results/call-controls-desktop-expanded.png" });
  await page.getByRole("navigation", { name: "页面模式" }).getByRole("button", { name: "全屏", exact: true }).click();
  await page.screenshot({ path: "test-results/call-controls-fullscreen-buttons.png" });
  await page.getByRole("button", { name: "展开文字输入" }).click();
  await expect.poll(() => page.evaluate(() => {
    const caption = document.getElementById("caption")!.getBoundingClientRect();
    const dock = document.getElementById("dock")!.getBoundingClientRect();
    return caption.bottom <= dock.top;
  })).toBe(true);
  await page.waitForTimeout(650);
  await page.screenshot({ path: "test-results/call-controls-fullscreen-expanded.png" });
});


test("persistent input stays visible after sending and on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  const input = page.getByRole("textbox", { name: "输入对话消息" });
  for (const name of ["并排", "内容"]) {
    await page.getByRole("navigation", { name: "页面模式" }).getByRole("button", { name, exact: true }).click();
    await expect(input).toBeVisible();
    await input.fill("补充安排");
    await input.press("Enter");
    await expect(input).toBeVisible();
    await expect(input).toBeEmpty();
    const box = await input.boundingBox();
    expect(box!.width).toBeGreaterThan(70);
    const dock = await page.locator("#dock").boundingBox();
    expect(dock!.x).toBeGreaterThanOrEqual(0);
    expect(dock!.x + dock!.width).toBeLessThanOrEqual(390);
  }
  await page.screenshot({ path: "test-results/call-controls-mobile-persistent.png" });
});

import { expect, test } from "@playwright/test";

test("home mode switching keeps the session workbench closed", async ({ page }) => {
  await page.goto("/");

  const workbench = page.getByRole("region", { name: "会话配置工作台" });
  const homeModeSwitch = page.getByRole("navigation", { name: "主页呈现模式" });
  await expect(workbench).toHaveAttribute("data-state", "collapsed");

  await homeModeSwitch.getByRole("button", { name: "数字人", exact: true }).click();

  await expect(workbench).toHaveAttribute("data-state", "collapsed");
});

test("session workbench shows every playable Samantha companion action", async ({ page }) => {
  const samanthaId = "avatar-8657be31-306e-428d-a013-7521e710ab6a";
  const savedActions = ["侧头微笑", "柔和回应", "忧郁共鸣"].map((displayName, index) => ({
    avatar_action_id: `saved-action-${index}`,
    display_name: displayName,
    video_url: `/api/avatar-assets/artifacts/saved-action-${index}`,
    pending_model_count: 0,
    created_at: "2026-09-02T08:00:00.000Z",
    deleted_at: null,
  }));
  const pendingActions = ["甜美元气", "纯欲柔光", "冷艳夜色", "知性温柔"].map((displayName, index) => ({
    avatar_action_id: `pending-action-${index}`,
    display_name: displayName,
    video_url: null,
    pending_model_count: 1,
    created_at: "2026-09-02T08:00:00.000Z",
    deleted_at: null,
  }));
  await page.route("**/api/avatars", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        avatars: [{
          avatar_id: samanthaId,
          display_name: "萨曼莎",
          source_image_url: "/digital-human/avatar1.png",
          created_at: "2026-09-02T08:00:00.000Z",
          updated_at: "2026-09-02T08:00:00.000Z",
          deleted_at: null,
          realtime_binding: null,
          actions: [...savedActions, ...pendingActions],
        }],
      }),
    });
  });

  await page.goto("/");
  await page.getByRole("navigation", { name: "主页呈现模式" })
    .getByRole("button", { name: "数字人", exact: true }).click();
  await page.getByRole("button", { name: "展开会话配置工作台" }).click();
  const workbench = page.getByRole("region", { name: "会话配置工作台" });
  await workbench.getByRole("button", { name: /多段式合成/ }).click();

  const samanthaCard = workbench.getByRole("article", { name: "萨曼莎 形象与动作" });
  await expect(samanthaCard.getByRole("button", { name: "浏览 萨曼莎 的形象与动作" }))
    .toHaveText("9 个动作");
  await samanthaCard.getByRole("button", { name: "展开 萨曼莎 的形象和动作" }).click();
  for (const actionName of ["甜美元气", "清新田园", "浪漫轻法式", "纯欲柔光", "冷艳夜色", "知性温柔", "侧头微笑", "柔和回应", "忧郁共鸣"]) {
    await expect(samanthaCard.getByRole("button", { name: `预览动作：${actionName}` })).toBeVisible();
  }

  await samanthaCard.getByRole("button", { name: "浏览 萨曼莎 的下一个媒体" }).click();
  await samanthaCard.getByRole("button", { name: "确认使用动作：甜美元气" }).click();
  await expect(samanthaCard.getByRole("button", { name: "预览动作：甜美元气" })).toHaveAttribute("aria-current", "true");
});

test("clicking the blank home preview closes the session workbench", async ({ page }) => {
  await page.goto("/");

  const workbench = page.getByRole("region", { name: "会话配置工作台" });
  await page.getByRole("button", { name: "展开会话配置工作台" }).click();
  await expect(workbench).toHaveAttribute("data-state", "compact");

  await page.locator(".app-shell").click({ position: { x: 1100, y: 350 } });

  await expect(workbench).toHaveAttribute("data-state", "collapsed");
});

test("switching configuration categories preserves the compact panel size", async ({ page }) => {
  await page.goto("/");

  const workbench = page.getByRole("region", { name: "会话配置工作台" });
  await expect(workbench).toHaveAttribute("data-state", "collapsed");
  await page.getByRole("button", { name: "展开会话配置工作台" }).click();
  await expect(workbench).toHaveAttribute("data-state", "compact");

  for (const category of ["音色", "模型", "工具", "对话", "通用"]) {
    await workbench.getByRole("button", { name: category, exact: true }).click();
    await expect(workbench).toHaveAttribute("data-state", "compact");
  }
});

test("general settings adjust the workbench transparency without hiding its content", async ({ page }) => {
  await page.goto("/");

  const workbench = page.getByRole("region", { name: "会话配置工作台" });
  await page.getByRole("button", { name: "展开会话配置工作台" }).click();
  await workbench.getByRole("button", { name: "通用", exact: true }).click();

  const transparency = workbench.getByRole("slider", { name: "工作台透明度" });
  const glassBlur = workbench.getByRole("slider", { name: "毛玻璃模糊" });
  const homeModeSwitch = page.getByRole("navigation", { name: "主页呈现模式" });
  const initialModeSurface = await homeModeSwitch.evaluate((element) => {
    const styles = window.getComputedStyle(element);
    return { background: styles.background, backdropFilter: styles.backdropFilter };
  });
  await expect(transparency).toHaveValue("70");
  await expect(glassBlur).toHaveValue("10");
  await transparency.fill("80");
  await glassBlur.fill("12");
  await expect(workbench).toHaveAttribute("data-transparency", "80");
  await expect(workbench).toHaveAttribute("data-glass-blur", "12");
  await expect(homeModeSwitch).toHaveAttribute("data-transparency", "80");
  await expect(homeModeSwitch).toHaveAttribute("data-glass-blur", "12");
  const updatedModeSurface = await homeModeSwitch.evaluate((element) => {
    const styles = window.getComputedStyle(element);
    return { background: styles.background, backdropFilter: styles.backdropFilter };
  });
  expect(updatedModeSurface.background).not.toBe(initialModeSurface.background);
  expect(updatedModeSurface.backdropFilter).not.toBe(initialModeSurface.backdropFilter);
  await expect(workbench.getByLabel("帮助：提高后可看到更多主页预览，文字与控件保持清晰。")).toBeVisible();
  await expect(workbench.getByLabel("帮助：降低后可保留更多背景动效细节，提高后文字衬底更稳定。")).toBeVisible();

  await page.reload();
  await page.getByRole("button", { name: "展开会话配置工作台" }).click();
  await workbench.getByRole("button", { name: "通用", exact: true }).click();
  await expect(workbench.getByRole("slider", { name: "工作台透明度" })).toHaveValue("80");
  await expect(workbench.getByRole("slider", { name: "毛玻璃模糊" })).toHaveValue("12");
});

test("model providers use a compact dropdown and update interface defaults", async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("openrealtime-persona-config-draft", JSON.stringify({
      ttsProvider: "bailian",
      bailianVoice: "__active_bailian_clone__",
      bailianVoiceLabel: "Shuchang 克隆音色",
    }));
  });
  await page.goto("/");
  await page.getByRole("button", { name: "数字人", exact: true }).click();

  const workbench = page.getByRole("region", { name: "会话配置工作台" });
  await page.getByRole("button", { name: "展开会话配置工作台" }).click();
  await workbench.getByRole("button", { name: "模型", exact: true }).click();

  const provider = workbench.getByRole("button", { name: "模型供应商" });
  await expect(provider).toContainText("DeepSeek");
  await provider.click();
  await workbench.getByRole("option", { name: "Anthropic" }).click();
  await expect(provider).toContainText("Anthropic");
  await workbench.getByText("模型与接口定义", { exact: true }).click();
  await expect(workbench.getByRole("textbox", { name: "大模型 Model ID" })).toHaveValue("claude-sonnet-5");
});

test("deduplicates the active Bailian clone and exposes rename and delete management", async ({ page }) => {
  const voiceId = "cosyvoice-v3-flash-shuchang-123";
  await page.route("**/api/voice-clones", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        provider: "bailian",
        configured: true,
        missing: [],
        targetModel: "cosyvoice-v3-flash",
        activeVoiceId: voiceId,
        voices: [{
          id: voiceId,
          displayName: "shuchang 克隆音色",
          status: "OK",
          createdAt: "2026-08-22 14:05:47",
        }],
      }),
    });
  });
  await page.goto("/");

  const workbench = page.getByRole("region", { name: "会话配置工作台" });
  await page.getByRole("button", { name: "展开会话配置工作台" }).click();
  await workbench.getByRole("button", { name: "音色", exact: true }).click();
  const builtInList = workbench.getByLabel("内置音色列表");
  const builtInChoice = builtInList.locator("button.provider-voice-select").filter({ hasText: "龙应沐 V3" });
  await builtInChoice.click();
  await expect(builtInChoice).toHaveAttribute("aria-pressed", "true");
  await expect(builtInChoice).toContainText("已选中");
  const selectedBuiltInStyles = await builtInChoice.locator("..").evaluate((element) => {
    const styles = window.getComputedStyle(element);
    return { backgroundImage: styles.backgroundImage, boxShadow: styles.boxShadow };
  });
  expect(selectedBuiltInStyles.backgroundImage).not.toBe("none");
  expect(selectedBuiltInStyles.boxShadow).not.toBe("none");
  await expect(workbench.locator("footer")).toContainText("龙应沐 V3");
  const cloneList = workbench.getByLabel("克隆音色列表");

  await expect(cloneList.locator("strong")).toHaveText(["shuchang 克隆音色"]);
  const cloneChoice = cloneList.getByRole("button", { name: /^shuchang 克隆音色/ });
  await cloneChoice.click();
  await expect(cloneChoice).toHaveAttribute("aria-pressed", "true");
  const selectedCloneRow = cloneChoice.locator("..");
  await expect(selectedCloneRow).toHaveAttribute("data-selected", "true");
  await expect(cloneChoice).toContainText("已选中");
  const selectedStyles = await selectedCloneRow.evaluate((element) => {
    const styles = window.getComputedStyle(element);
    return { backgroundImage: styles.backgroundImage, boxShadow: styles.boxShadow };
  });
  expect(selectedStyles.backgroundImage).not.toBe("none");
  expect(selectedStyles.boxShadow).not.toBe("none");
  await expect(workbench.locator("footer")).toContainText("shuchang 克隆音色");
  await cloneList.getByRole("button", { name: "重命名 shuchang 克隆音色" }).click();
  await expect(cloneList.getByRole("textbox", { name: "新的音色名称：shuchang 克隆音色" })).toHaveValue("shuchang 克隆音色");
  await cloneList.getByRole("button", { name: "取消" }).click();
  await cloneList.getByRole("button", { name: "删除 shuchang 克隆音色" }).click();
  const dialog = page.getByRole("alertdialog", { name: "确认删除这个克隆音色？" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("shuchang 克隆音色");
  await expect(dialog).toContainText("无法恢复");
  await expect(dialog.getByRole("button", { name: "取消" })).toBeFocused();
});

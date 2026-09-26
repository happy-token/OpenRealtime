import { expect, test, type Page } from "@playwright/test";

async function selectAvatarMode(page: Page, name: "离线" | "离线加口型" | "实时") {
  await page.evaluate((mode) => {
    localStorage.setItem("voice-agent-experience-mode", "avatar");
    const current = JSON.parse(localStorage.getItem("voice-agent-avatar-display-config") || "{}") as Record<string, unknown>;
    localStorage.setItem("voice-agent-avatar-display-config", JSON.stringify({
      ...current,
      renderPath: mode === "实时" ? "hosted" : mode === "离线" ? "orchestrated" : "segmented",
      segmentedAvatarId: "companion",
      segmentedAvatarActionId: "builtin:opentalking:companion",
    }));
  }, name);
  await page.reload();
}

test("conversation uses sidebar settings rather than the old advanced panel", async ({ page }) => {
  await page.goto("/conversation");
  await expect(page.getByRole("button", { name: "打开高级设置" })).toHaveCount(0);
  await page.getByRole("button", { name: /本地用户/ }).click();
  await page.getByRole("link", { name: "设置", exact: true }).click();
  await expect(page).toHaveURL(/\/settings$/);
  for (const name of ["供应商", "外观", "Memory 与隐私", "高级配置"]) {
    await expect(page.getByRole("link", { name: new RegExp(name) })).toBeVisible();
  }
});

test("home action panel includes actions awaiting adaptation and excludes actions without video", async ({ page }) => {
  const samanthaId = "avatar-8657be31-306e-428d-a013-7521e710ab6a";
  const savedActions = ["已保存动作一", "已保存动作二", "已保存动作三"].map((displayName, index) => ({
    avatar_action_id: `saved-action-${index}`,
    display_name: displayName,
    video_url: `/api/avatar-assets/artifacts/saved-action-${index}`,
    pending_model_count: 0,
    created_at: "2026-09-02T08:00:00.000Z",
    deleted_at: null,
  }));
  const pendingActions = ["待生成动作一", "待生成动作二"].map((displayName, index) => ({
    avatar_action_id: `pending-action-${index}`,
    display_name: displayName,
    video_url: null,
    pending_model_count: 1,
    created_at: "2026-09-02T08:00:00.000Z",
    deleted_at: null,
  }));
  const adaptingAction = {
    avatar_action_id: "adapting-action",
    display_name: "开始前适配动作",
    video_url: "/api/avatar-assets/artifacts/adapting-action",
    pending_model_count: 1,
    created_at: "2026-09-02T08:00:00.000Z",
    deleted_at: null,
  };
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
          actions: [...savedActions, adaptingAction, ...pendingActions],
        }],
      }),
    });
  });

  await page.goto("/");
  await selectAvatarMode(page, "离线加口型");
  await page.getByRole("button", { name: "打开数字人形象" }).click();
  const avatarPanel = page.getByRole("complementary", { name: "数字人形象" });
  await avatarPanel.getByRole("button", { name: "选择萨曼莎" }).click();
  await page.getByRole("button", { name: "打开动作列表" }).click();
  const actionPanel = page.getByRole("complementary", { name: "动作" });
  for (const actionName of savedActions.map((action) => action.display_name)) {
    await expect(actionPanel.getByRole("button", { name: `选择${actionName}` })).toBeVisible();
  }
  const adaptingChoice = actionPanel.getByRole("button", { name: "选择开始前适配动作" });
  await expect(adaptingChoice).toBeVisible();
  await adaptingChoice.click();
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem("voice-agent-avatar-display-config") || "{}") as { segmentedAvatarActionId?: string }))
    .toMatchObject({ segmentedAvatarActionId: "adapting-action" });
  await expect(actionPanel.getByRole("button", { name: "选择待生成动作一" })).toHaveCount(0);
});

test("appearance settings persist and affect the conversation preview", async ({ page }) => {
  await page.goto("/settings/appearance");
  await page.getByRole("radio", { name: "音频柱" }).click();
  await page.getByRole("slider", { name: /全站玻璃透明度/ }).fill("55");
  await page.getByRole("slider", { name: /全站玻璃模糊/ }).fill("12");
  await page.reload();
  await expect(page.getByRole("radio", { name: "音频柱" })).toHaveAttribute("aria-checked", "true");
  await expect(page.getByRole("slider", { name: /全站玻璃透明度/ })).toHaveValue("55");
  await page.goto("/conversation");
  await expect(page.locator('[data-orb-theme="bars"]').first()).toBeVisible();
});

test("provider model draft retains interface defaults", async ({ page }) => {
  await page.goto("/settings/providers");
  await page.getByLabel("模型供应商").selectOption("anthropic");
  await expect(page.getByLabel("Model ID", { exact: true })).toHaveValue("claude-sonnet-5");
  await page.reload();
  await expect(page.getByLabel("模型供应商")).toHaveValue("anthropic");
  await expect(page.getByLabel("Model ID", { exact: true })).toHaveValue("claude-sonnet-5");
});

test("advanced settings persist new conversation defaults", async ({ page }) => {
  await page.goto("/settings/advanced");
  await page.getByRole("slider", { name: /本地播放音量/ }).fill("45");
  await page.getByRole("checkbox", { name: "允许随时打断" }).uncheck();
  await page.reload();
  await expect(page.getByRole("slider", { name: /本地播放音量/ })).toHaveValue("45");
  await expect(page.getByRole("checkbox", { name: "允许随时打断" })).not.toBeChecked();
});

test("clone voice management remains in the resource library", async ({ page }) => {
  await page.goto("/resources?tab=voices");
  await page.getByRole("button", { name: "新建或克隆声音" }).click();
  await expect(page.getByText("克隆音色", { exact: true }).first()).toBeVisible();
});

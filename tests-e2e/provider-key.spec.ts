import { expect, test } from "@playwright/test";

test("asks for a MiniMax key only when generation starts and cancel does not submit", async ({ page }) => {
  const avatar = {
    avatar_id: "companion",
    display_name: "陪伴",
    source_image_url: "/digital-human/opentalking/companion/reference.png",
    created_at: "2026-08-29T00:00:00.000Z",
    updated_at: "2026-08-29T00:00:00.000Z",
    deleted_at: null,
    actions: [],
    realtime_binding: null,
  };
  let submissions = 0;
  await page.route("**/api/avatars/companion", (route) => route.fulfill({ json: { avatar } }));
  await page.route("**/api/liveportrait", (route) => route.fulfill({ json: { ready: true, templates: [] } }));
  await page.route("**/api/ltx/image-to-video", (route) => route.request().method() === "GET"
    ? route.fulfill({ json: { ready: true } })
    : (submissions++, route.fulfill({ status: 202, json: { task_id: "test-task", state: "queueing" } })));

  await page.goto("/avatars/create?task=action&avatar_id=companion");
  const studio = page.getByRole("region", { name: "动作创作" });
  await studio.getByRole("tab", { name: /视频生成/ }).click();
  const generate = studio.getByRole("button", { name: "生成动作" });
  await expect(generate).toBeEnabled();
  await generate.click();
  const dialog = page.getByRole("dialog", { name: "连接 MiniMax 视频生成" });
  await expect(dialog).toBeVisible();
  await expect.poll(() => submissions).toBe(0);
  await dialog.getByRole("button", { name: "取消" }).click();
  await expect(dialog).toHaveCount(0);
  await generate.click();
  await dialog.getByRole("textbox", { name: "API Key" }).fill("user-minimax-test-key");
  await dialog.getByRole("button", { name: "继续" }).click();
  await expect(dialog).toHaveCount(0);
  await expect.poll(() => submissions).toBe(1);
});

test("offers the Anam signup link before creating a realtime avatar", async ({ page }) => {
  const avatar = {
    avatar_id: "companion", display_name: "陪伴",
    source_image_url: "/digital-human/opentalking/companion/reference.png",
    created_at: "2026-08-29T00:00:00.000Z", updated_at: "2026-08-29T00:00:00.000Z",
    deleted_at: null, actions: [], realtime_binding: null,
  };
  let submissions = 0;
  await page.route("**/api/avatars/companion", (route) => route.fulfill({ json: { avatar } }));
  await page.route("**/api/anam/avatars", (route) => route.request().method() === "POST"
    ? (submissions++, route.fulfill({ status: 201, json: { avatar: { id: "anam-companion", displayName: "陪伴数字人", activeVersion: "cara-4", videoUrl: null } } }))
    : route.fulfill({ json: { avatars: [], total: 0 } }));
  await page.goto("/avatars/create?task=realtime&avatar_id=companion");
  await page.getByRole("button", { name: "创建实时驱动形象", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "连接 Anam 实时数字人" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("link", { name: /免费体验额度/ })).toHaveAttribute("href", "https://anam.ai/");
  expect(submissions).toBe(0);
  await dialog.getByRole("textbox", { name: "API Key" }).fill("user-anam-test-key");
  await dialog.getByRole("button", { name: "继续" }).click();
  await expect.poll(() => submissions).toBe(1);
});

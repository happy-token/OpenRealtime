import { expect, test } from "@playwright/test";

function createAvatar(variantCount: number) {
  const variants = Array.from({ length: variantCount }, (_, index) => ({
    id: `material-${index}`,
    display_name: `讲话版本 ${index + 1}`,
    method: "musetalk",
    source_video_url: "/motion.mp4",
    video_url: `/material-${index}.mp4`,
    deleted_at: null as string | null,
  }));
  const action = {
    avatar_action_id: "base-action", display_name: "测试动作", video_url: "/motion.mp4",
    pending_model_count: 0, created_at: "2026-09-11", deleted_at: null, talking_variants: variants,
  };
  const avatar = {
    avatar_id: "avatar-detail-test", display_name: "测试形象",
    source_image_url: "/digital-human/opentalking/companion/reference.png",
    created_at: "2026-09-11", updated_at: "2026-09-11", deleted_at: null, realtime_binding: null,
    actions: [action, { ...action, avatar_action_id: "second-action", display_name: "其他动作", talking_variants: [] }],
  };
  return { action, avatar, variants };
}

test("previews and deletes the selected talking material inside the detail stage", async ({ page }) => {
  const { action, avatar, variants } = createAvatar(1);
  variants[0].display_name = "测试动作 · MuseTalk 1.5";
  await page.route("**/api/avatars", route => route.fulfill({ json: { avatars: [avatar] } }));
  await page.route("**/api/avatars/avatar-detail-test", route => route.fulfill({ json: { avatar } }));
  await page.route("**/api/avatars/avatar-detail-test/actions/base-action/talking-variants/**", route => {
    const payload = route.request().postDataJSON();
    if (payload.operation === "rename") variants[0].display_name = payload.displayName.trim();
    else variants[0].deleted_at = payload.operation === "trash" ? "2026-09-20T00:00:00.000Z" : null;
    return route.fulfill({ json: { action: { ...action, talking_variants: variants } } });
  });

  await page.goto("/avatars/avatar-detail-test?avatar_action_id=base-action");
  const stage = page.getByRole("region", { name: "测试形象 媒体舞台" });
  const rail = stage.getByRole("complementary", { name: "测试动作素材切换" });
  const materials = rail.getByRole("group", { name: "测试动作讲话素材选择" });
  const operations = rail.getByRole("group", { name: "讲话素材操作" });
  const picker = materials.locator("[data-rwp]");
  await expect(rail).toBeVisible();
  await expect(materials.locator('[data-rwp-option][data-index="0"]')).toContainText("底片");
  await expect(materials.locator('[data-rwp-option][data-index="1"]')).toContainText("MuseTalk 1.5");
  await expect(materials.locator('[data-rwp-option][data-index="1"]')).not.toContainText("测试动作 ·");
  await expect(rail.getByRole("status")).toContainText("当前预览：测试动作动作底片");
  await expect(operations.getByRole("button", { name: "请先选择讲话素材再删除" })).toBeDisabled();
  await picker.locator('[data-rwp-option][data-index="1"]').click();
  await expect(rail.getByRole("status")).toContainText("当前预览：测试动作 · MuseTalk 1.5");
  await expect(stage.getByLabel("测试形象 · 测试动作 · MuseTalk 1.5 讲话素材")).toHaveAttribute("src", "/material-0.mp4");

  await expect(operations.getByRole("link", { name: "生成讲话素材" })).toHaveAttribute("href", /task=lightweight/);
  await operations.getByRole("button", { name: "修改讲话素材名称：测试动作 · MuseTalk 1.5" }).click();
  await page.getByRole("dialog", { name: "修改讲话素材名称" }).getByRole("textbox", { name: "新的讲话素材名称" }).fill("晨间版");
  await page.getByRole("dialog", { name: "修改讲话素材名称" }).getByRole("button", { name: "保存名称" }).click();
  await expect(materials.locator('[data-rwp-option][data-index="1"]')).toContainText("晨间版");
  await expect(stage.getByLabel("测试形象 · 晨间版 讲话素材")).toHaveAttribute("src", "/material-0.mp4");
  await operations.getByRole("button", { name: "删除讲话素材：晨间版" }).click();
  await expect(page.getByRole("dialog", { name: "删除讲话素材" })).toContainText("动作底片和其他讲话版仍可使用");
  await page.getByRole("dialog", { name: "删除讲话素材" }).getByRole("button", { name: "移入已删除讲话素材" }).click();
  await expect(stage.getByLabel("测试形象 · 测试动作", { exact: true })).toHaveAttribute("src", "/motion.mp4");
  await rail.locator("summary").click();
  await rail.getByRole("button", { name: "恢复讲话素材：晨间版" }).click();
  await expect(picker.locator("[data-rwp-option]")).toHaveCount(2);

  await page.getByRole("button", { name: "查看动作：其他动作" }).click();
  await expect(stage.getByRole("complementary", { name: "其他动作素材切换" }).getByText("此动作还没有讲话素材")).toBeVisible();
});

test("keeps the wheel picker scrollable above the media dock on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 740 });
  const { avatar } = createAvatar(12);
  await page.route("**/api/avatars", route => route.fulfill({ json: { avatars: [avatar] } }));
  await page.route("**/api/avatars/avatar-detail-test", route => route.fulfill({ json: { avatar } }));

  await page.goto("/avatars/avatar-detail-test");
  const stage = page.getByRole("region", { name: "测试形象 媒体舞台" });
  const rail = stage.getByRole("complementary", { name: "测试动作素材切换" });
  const list = rail.getByRole("region", { name: "讲话素材列表" });
  const materials = list.getByRole("group", { name: "测试动作讲话素材选择" });
  const picker = materials.locator("[data-rwp]");
  await expect(list).toBeVisible();
  await expect(picker.locator("[data-rwp-option]")).toHaveCount(13);
  const [railBounds, stageBounds] = await Promise.all([rail.boundingBox(), stage.boundingBox()]);
  expect(railBounds && stageBounds && railBounds.y + railBounds.height < stageBounds.y + stageBounds.height - 140).toBe(true);

  await picker.hover();
  await page.mouse.wheel(0, 120);
  await expect(stage.getByLabel("测试形象 · 讲话版本 1 讲话素材")).toHaveAttribute("src", "/material-0.mp4");
  await picker.focus();
  await picker.press("End");
  await expect(stage.getByLabel("测试形象 · 讲话版本 12 讲话素材")).toHaveAttribute("src", "/material-11.mp4");
  await expect(rail.getByRole("status")).toContainText("当前预览：讲话版本 12");
  await picker.press("ArrowUp");
  await expect(rail.getByRole("status")).toContainText("当前预览：讲话版本 11");
  await picker.press("Home");
  await expect(stage.getByLabel("测试形象 · 测试动作", { exact: true })).toHaveAttribute("src", "/motion.mp4");
});

test("distinguishes the two top-right delete actions and requires confirmation", async ({ page }) => {
  const { avatar } = createAvatar(1);
  await page.route("**/api/avatars", route => route.fulfill({ json: { avatars: [avatar] } }));
  await page.route("**/api/avatars/avatar-detail-test", route => route.fulfill({ json: { avatar } }));
  let deleteRequests = 0;
  await page.route("**/api/avatars/avatar-detail-test/actions/base-action", route => {
    deleteRequests += 1;
    return route.fulfill({ json: { action: avatar.actions[0] } });
  });

  await page.goto("/avatars/avatar-detail-test?avatar_action_id=base-action");
  const stage = page.getByRole("region", { name: "测试形象 媒体舞台" });
  const deleteAction = stage.getByRole("button", { name: "删除当前动作：测试动作" });
  const deleteAvatar = stage.getByRole("button", { name: "删除数字人资产：测试形象" });
  await expect(deleteAction).toContainText("删除当前动作");
  await expect(deleteAvatar).toContainText("删除数字人");
  page.once("dialog", async dialog => {
    expect(dialog.message()).toContain("数字人和其他动作不受影响");
    await dialog.dismiss();
  });
  await deleteAction.click();
  page.once("dialog", async dialog => {
    expect(dialog.message()).toContain("其所有动作和讲话素材也会暂时不可用");
    await dialog.dismiss();
  });
  await deleteAvatar.click();
  expect(deleteRequests).toBe(0);
  await expect(stage.getByRole("complementary", { name: "测试动作素材切换" })).toBeVisible();
});

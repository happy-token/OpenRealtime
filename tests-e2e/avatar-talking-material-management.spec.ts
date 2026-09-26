import { expect, test } from "@playwright/test";

test("manages one talking material under its parent action", async ({ page }) => {
  const variant = {
    id: "musetalk-1fdf9773-fb3e-4f3c-927e-b8eb530b6714",
    display_name: "柔和回应 · MuseTalk 1.5",
    method: "musetalk",
    source_video_url: "/digital-human/opentalking/companion/motion.mp4",
    video_url: "/digital-human/talking-variants/musetalk-1fdf9773-fb3e-4f3c-927e-b8eb530b6714.mp4",
    processing: "original",
    validation: "pending",
    deleted_at: null as string | null,
  };
  const action = {
    avatar_action_id: "base-action", display_name: "柔和回应", video_url: variant.source_video_url,
    pending_model_count: 0, created_at: "2026-09-11", deleted_at: null, talking_variants: [variant],
  };
  const secondAction = {
    avatar_action_id: "second-action", display_name: "挥手", video_url: variant.source_video_url,
    pending_model_count: 0, created_at: "2026-09-11", deleted_at: null, talking_variants: [],
  };
  const avatar = {
    avatar_id: "avatar-test", display_name: "测试形象", source_image_url: "/digital-human/opentalking/companion/reference.png",
    created_at: "2026-09-11", updated_at: "2026-09-11", deleted_at: null, realtime_binding: null, actions: [action, secondAction],
  };
  await page.route("**/api/avatars", route => route.fulfill({ json: { avatars: [avatar] } }));
  await page.route("**/api/avatars/avatar-test", route => route.fulfill({ json: { avatar } }));
  await page.route("**/api/avatars/avatar-test/actions/base-action/talking-variants/**", route => {
    const operation = route.request().postDataJSON().operation;
    variant.deleted_at = operation === "trash" ? "2026-09-20T00:00:00.000Z" : null;
    return route.fulfill({ json: { action: { ...action, talking_variants: [{ ...variant }] } } });
  });

  await page.goto("/avatars?scope=internal-preset");
  const trigger = page.getByRole("button", { name: "选择 测试形象 的讲话素材" });
  await expect(trigger).toBeVisible();
  await trigger.click();
  const rail = page.getByRole("complementary", { name: "柔和回应素材切换" });
  await expect(rail.getByRole("button", { name: "预览讲话素材：柔和回应 · MuseTalk 1.5" })).toBeVisible();
  await rail.getByRole("button", { name: "预览讲话素材：柔和回应 · MuseTalk 1.5" }).click();
  await expect(page.getByLabel("测试形象 · 柔和回应 · MuseTalk 1.5 讲话素材")).toHaveAttribute("src", variant.video_url);
  await trigger.click();
  await expect(rail).toHaveCount(0);
  await expect(page.getByLabel("测试形象 · 柔和回应 · MuseTalk 1.5 讲话素材")).toHaveAttribute("src", variant.video_url);
  await trigger.click();
  await expect(page).toHaveURL(/\/avatars\?scope=internal-preset$/);
  await rail.getByRole("button", { name: "预览动作底片：柔和回应" }).click();
  await page.getByRole("button", { name: "浏览 测试形象 的下一个媒体" }).click();
  await expect(page.getByRole("complementary", { name: "挥手素材切换" }).getByText("此动作还没有讲话素材")).toBeVisible();
  await page.getByRole("button", { name: "浏览 测试形象 的上一个媒体" }).click();
  await expect(rail).toBeVisible();
  await rail.getByRole("button", { name: "预览讲话素材：柔和回应 · MuseTalk 1.5" }).click();
  await rail.getByRole("button", { name: "删除讲话素材：柔和回应 · MuseTalk 1.5" }).click();
  await page.getByRole("dialog", { name: "删除讲话素材" }).getByRole("button", { name: "移入已删除讲话素材" }).click();
  await expect(rail.getByText("此动作还没有讲话素材")).toBeVisible();
  await expect(rail.getByRole("button", { name: "预览动作底片：柔和回应" })).toHaveAttribute("aria-pressed", "true");
  await rail.locator("summary").click();
  await rail.getByRole("button", { name: "恢复讲话素材：柔和回应 · MuseTalk 1.5" }).click();
  await expect(rail.getByRole("button", { name: "删除讲话素材：柔和回应 · MuseTalk 1.5" })).toBeVisible();
  await expect(rail.getByRole("link", { name: "生成讲话素材" })).toHaveAttribute("href", "/avatars/create?task=lightweight&avatar_id=avatar-test&avatar_action_id=base-action");
});

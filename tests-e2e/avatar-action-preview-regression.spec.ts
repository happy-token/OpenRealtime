import { expect, test } from "@playwright/test";

test("plays an internal action preview and preserves the source aspect ratio", async ({ page }) => {
  await page.goto("/avatars?scope=internal-preset");
  const card = page.getByRole("article").filter({ has: page.getByRole("heading", { name: "陪伴" }) });
  await expect(card.getByRole("button", { name: /管理 陪伴 的/ })).toBeVisible();
  await card.getByRole("button", { name: /管理 陪伴 的/ }).click();
  const video = card.locator('video[data-playing="true"]');
  await expect(video).toBeVisible();
  await expect.poll(() => video.evaluate((node) => {
    const element = node as HTMLVideoElement;
    return element.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA && !element.paused && element.currentTime > 0;
  })).toBe(true);
  const media = await video.evaluate((node) => {
    const element = node as HTMLVideoElement;
    return { sourceRatio: element.videoWidth / element.videoHeight, fit: getComputedStyle(element).objectFit };
  });
  expect(media.sourceRatio).toBeCloseTo(538 / 878, 2);
  expect(media.fit).toBe("contain");
});

test("keeps action thumbnails uncropped on the avatar detail page", async ({ page }) => {
  const avatar = {
    avatar_id: "test-avatar",
    display_name: "陪伴",
    source_image_url: "/digital-human/opentalking/companion/reference.png",
    created_at: "2026-08-29T00:00:00.000Z",
    updated_at: "2026-08-29T00:00:00.000Z",
    deleted_at: null,
    realtime_binding: null,
    actions: [{
      avatar_action_id: "companion-motion",
      display_name: "内置动作",
      video_url: "/digital-human/opentalking/companion/motion.mp4",
      pending_model_count: 0,
      created_at: "2026-08-29T00:00:00.000Z",
      deleted_at: null,
    }],
  };
  await page.route("**/api/avatars", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ avatars: [avatar] }) });
  });
  await page.route("**/api/avatars/test-avatar", async (route) => {
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ avatar }) });
  });
  await page.goto("/avatars/test-avatar");
  const preview = page.getByLabel("陪伴 · 内置动作 缩略预览", { exact: true });
  await expect(preview).toBeVisible();
  expect(await preview.evaluate((node) => getComputedStyle(node).objectFit)).toBe("contain");
  await page.getByRole("button", { name: "查看动作：内置动作" }).click();
  const stage = page.getByLabel("陪伴 · 内置动作", { exact: true });
  await expect.poll(() => stage.evaluate((node) => !(node as HTMLVideoElement).paused)).toBe(true);
});

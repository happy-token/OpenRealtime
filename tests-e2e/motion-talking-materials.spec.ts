import { test, expect } from "@playwright/test";
const avatarId = "avatar-8657be31-306e-428d-a013-7521e710ab6a";
const source = "/digital-human/builtin-motion/avatar-bundled.mp4";
const variant = { id: "muse-test", display_name: "柔和回应 · MuseTalk 1.5", method: "musetalk", source_video_url: source, video_url: "/digital-human/talking-variants/soft-response-musetalk-v1.mp4", processing: "original", validation: "pending" };
function avatar(ready: boolean) {
  return { avatar_id: avatarId, display_name: "萨曼莎", source_image_url: "/digital-human/avatar1.png", created_at: "2026-09-11", updated_at: "2026-09-11", deleted_at: null, realtime_binding: null,
    actions: [{ avatar_action_id: "soft-action", display_name: "柔和回应", video_url: source, pending_model_count: 2, created_at: "2026-09-11", deleted_at: null, talking_variants: ready ? [variant] : [] }] };
}

test("MuseTalk generation saves the paired material and makes the talking preview available", async ({ page }) => {
  let ready = false;
  let submissions = 0;
  await page.route("**/api/avatars", route => route.fulfill({ json: { avatars: [avatar(ready)] } }));
  await page.route(`**/api/avatars/${avatarId}`, route => route.fulfill({ json: { avatar: avatar(ready) } }));
  // Every generation request is intercepted: this test never starts GPU work.
  await page.route("**/talking-variants/generate", route => {
    if (route.request().method() === "POST") {
      submissions++;
      return route.fulfill({ status: 202, json: { job: { id: "test-job", state: "processing" } } });
    }
    if (!submissions) return route.fulfill({ json: { job: null } });
    ready = true;
    return route.fulfill({ json: { job: { id: "test-job", state: "success", variant } } });
  });
  await page.goto(`/avatars/create?task=lightweight&avatar_id=${avatarId}`);
  await page.getByRole("button", { name: "待机动作 · 从资产库选择", exact: true }).click();
  await page.getByRole("option", { name: "柔和回应", exact: true }).click();
  await page.getByRole("button", { name: "生成 MuseTalk 讲话素材", exact: true }).click();
  await expect(page.getByRole("button", { name: "正在生成讲话素材…", exact: true })).toBeDisabled();
  await expect(page.getByText("MuseTalk 讲话素材已保存，可在会话配置中直接选择。")).toBeVisible();
  await expect(page.getByRole("button", { name: "讲话素材", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("video")).toHaveAttribute("src", variant.video_url);
  expect(submissions).toBe(1);
});

test("session picker selects talking material and persists its paired base without a second selector", async ({ page }) => {
  await page.route("**/api/avatars", route => route.fulfill({ json: { avatars: [avatar(true)] } }));
  await page.route("**/api/anam/avatars", route => route.fulfill({ json: { avatars: [] } }));
  await page.route("**/api/avatar-assets/actions", route => route.fulfill({ json: { actions: [], selection: null } }));
  await page.route("**/api/avatar-capabilities", route => route.fulfill({ json: Object.fromEntries(["assets", "anam", "heygen", "localRenderer"].map(key => [key, { state: "available", message: "ready" }])) }));
  await page.addInitScript(() => localStorage.setItem("voice-agent-experience-mode", "avatar"));
  await page.goto("/");
  await page.getByRole("button", { name: "展开会话配置工作台" }).click();
  await page.getByRole("button", { name: /动作编排/ }).click();
  const picker = page.getByRole("region", { name: "动作编排讲话素材" });
  await expect(picker.locator("video")).toHaveAttribute("src", variant.video_url);
  await picker.getByRole("button", { name: "确认使用讲话素材：柔和回应 · MuseTalk", exact: true }).click();
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem("voice-agent-avatar-display-config") || "{}"))).toMatchObject({ segmentedAvatarId: avatarId, segmentedAvatarActionId: "soft-action", motionTalkingVariantId: "muse-test" });
  await expect(page.getByRole("button", { name: "编排讲话素材", exact: true })).toHaveCount(0);
});

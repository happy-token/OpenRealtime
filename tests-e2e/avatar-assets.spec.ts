import { expect, test } from "@playwright/test";
import { resolve } from "node:path";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("openrealtime-language", "zh-CN"));
});

test.describe("Avatar asset MVP", () => {
  test("offers every segmented Avatar in the creation library", async ({ page }) => {
    await page.route("**/api/avatars", async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          avatars: [{
            avatar_id: "avatar-digital-human-1",
            display_name: "数字人1",
            source_image_url: "/digital-human/avatar1.png",
            created_at: "2026-08-31T00:00:00.000Z",
            updated_at: "2026-08-31T00:00:00.000Z",
            deleted_at: null,
            actions: [{
              avatar_action_id: "action-smile",
              display_name: "侧头微笑",
              video_url: "/digital-human/builtin-motion/shuchang-realtime-idle.mp4",
              pending_model_count: 0,
              created_at: "2026-08-31T00:00:00.000Z",
              deleted_at: null,
            }],
            realtime_binding: null,
          }],
        }),
      });
    });
    await page.route("**/api/anam/avatars", async (route) => {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ avatars: [] }) });
    });
    await page.route("**/api/avatar-assets/actions", async (route) => {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ actions: [], selection: null }) });
    });

    await page.goto("/avatars/create");

    await expect(page.getByRole("button", { name: "选择数字人1" })).toBeVisible();
  });

  test("reuses an existing Avatar selected from the creation library", async ({ page }) => {
    const avatar = {
      avatar_id: "avatar-digital-human-1",
      display_name: "数字人1",
      source_image_url: "/digital-human/avatar1.png",
      created_at: "2026-08-31T00:00:00.000Z",
      updated_at: "2026-08-31T00:00:00.000Z",
      deleted_at: null,
      actions: [{
        avatar_action_id: "action-smile",
        display_name: "侧头微笑",
        video_url: "/digital-human/builtin-motion/shuchang-realtime-idle.mp4",
        pending_model_count: 0,
        created_at: "2026-08-31T00:00:00.000Z",
        deleted_at: null,
      }],
      realtime_binding: null,
    };
    let createRequestCount = 0;
    await page.route("**/api/avatars", async (route) => {
      if (route.request().method() === "POST") {
        createRequestCount += 1;
        await route.fulfill({ contentType: "application/json", body: JSON.stringify({ avatar }) });
        return;
      }
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ avatars: [avatar] }) });
    });
    await page.route("**/api/avatars/avatar-digital-human-1", async (route) => {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ avatar }) });
    });
    await page.route("**/api/anam/avatars", async (route) => {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ avatars: [] }) });
    });
    await page.route("**/api/avatar-assets/actions", async (route) => {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ actions: [], selection: null }) });
    });

    await page.goto("/avatars/create");
    await page.getByRole("button", { name: "关闭创建形象窗口" }).click();
    await page.getByRole("button", { name: "选择数字人1" }).click();
    await expect(page.getByRole("heading", { name: "数字人1", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "选择数字人1" })).toHaveAttribute("aria-pressed", "true");
    expect(createRequestCount).toBe(0);
  });

  test("fills the creation visual canvas with the current Avatar preview", async ({ page }) => {
    await page.setViewportSize({ width: 760, height: 820 });
    await page.goto("/avatars/create");

    await page.getByRole("button", { name: "关闭创建形象窗口" }).click();
    await page.getByRole("button", { name: "选择萨曼莎", exact: true }).click();
    const preview = page.getByLabel("萨曼莎 动作预览", { exact: true });
    await expect(preview).toBeVisible();
    await expect.poll(() => preview.evaluate(node => getComputedStyle(node).objectFit)).toBe("cover");
    const previewBox = await preview.boundingBox();
    expect(previewBox).not.toBeNull();
    expect(previewBox!.width).toBeGreaterThan(200);
    expect(previewBox!.height).toBeGreaterThan(200);
  });

  test("expands the selected Avatar preview to the full browser window", async ({ page }) => {
    await page.goto("/avatars/create");

    const currentPreview = page.getByRole("group", { name: "内部预制形象" }).locator('[data-position="center"]');
    await currentPreview.click();
    await currentPreview.click();

    const dialog = page.getByRole("dialog", { name: /大图预览/ });
    await expect(dialog).toBeVisible();
    await page.waitForTimeout(350);
    const viewport = page.viewportSize();
    const dialogBox = await dialog.boundingBox();
    expect(viewport).not.toBeNull();
    expect(dialogBox).not.toBeNull();
    expect(dialogBox!.width).toBeGreaterThanOrEqual(viewport!.width - 2);
    expect(dialogBox!.height).toBeGreaterThanOrEqual(viewport!.height - 2);
  });

  test("hydrates stored Avatar display names without a server-client mismatch", async ({ page }) => {
    const hydrationErrors: string[] = [];
    page.on("console", (message) => {
      if (message.text().includes("Hydration failed")) {
        hydrationErrors.push(message.text());
      }
    });
    page.on("pageerror", (error) => {
      if (error.message.includes("Hydration failed")) hydrationErrors.push(error.message);
    });
    await page.addInitScript(() => {
      window.localStorage.setItem("openrealtime-avatar-identity-display-names", JSON.stringify({
        shuchang: "傻妞",
      }));
    });

    await page.goto("/avatars?scope=internal-preset");

    await expect(page.getByRole("heading", { name: "傻妞" })).toBeVisible();
    await page.waitForTimeout(500);
    expect(hydrationErrors).toEqual([]);
  });

  test("groups the two retained local portraits under internal presets", async ({ page }) => {
    await page.addInitScript(() => {
      window.localStorage.setItem("openrealtime-avatar-identity-display-names", JSON.stringify({
        shuchang: "傻妞",
        "office-woman": "赛博女友",
      }));
      window.localStorage.setItem("openrealtime-motion-asset-metadata-v1", JSON.stringify({
        version: 1,
        displayNames: {},
        hiddenIds: [],
        hiddenIdentityIds: [],
      }));
    });
    await page.route("**/api/anam/avatars", async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          avatars: [
            { id: "anam-mia", displayName: "Mia", origin: "official", activeVersion: "cara-4", imageUrl: "/mia.png" },
          ],
        }),
      });
    });
    await page.route("**/api/avatars", async (route) => {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ avatars: [] }) });
    });

    await page.goto("/avatars");
    await page.getByRole("button", { name: /内部预制形象/ }).click();

    await expect(page.getByRole("article")).toHaveCount(2);
    await expect(page.getByRole("heading", { name: "傻妞" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "陪伴" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "赛博女友" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Shuchang 测试形象" })).toHaveCount(0);

    const shuchangCard = page.getByRole("article").filter({ has: page.getByRole("heading", { name: "傻妞" }) });
    await shuchangCard.getByRole("button", { name: "管理 傻妞 的 1 个动作" }).click();
    const realtimeIdle = shuchangCard.getByRole("button", { name: "预览动作：实时待机" });
    await expect(realtimeIdle).toBeVisible();
    await expect(realtimeIdle.locator("video")).toHaveAttribute("src", "/digital-human/builtin-motion/shuchang-realtime-idle.mp4");
  });

  test("uses a full-card image preview with minimal management controls", async ({ page }) => {
    await page.goto("/avatars?scope=internal-preset");

    const pageTitle = page.getByRole("banner").getByRole("heading", { name: "数字人资产" });
    await expect(pageTitle).toBeVisible();
    await expect(page.locator("main h1")).toHaveCount(0);
    await expect(page.getByText("按驱动方式管理 Avatar：供应商实时生成，或使用内部预制形象进入多段式合成。")).toHaveCount(0);

    const card = page.getByRole("article").filter({ has: page.getByRole("heading", { name: "陪伴" }) });
    await expect(card.getByText("形象", { exact: true })).toHaveCount(0);
    const image = card.getByRole("img", { name: "陪伴 形象" });
    const name = card.getByRole("heading", { name: "陪伴" });
    const actionCount = card.getByRole("button", { name: "管理 陪伴 的 1 个动作" });
    const moreButton = card.getByRole("button", { name: "更多操作：陪伴" });
    const cardBox = await card.boundingBox();
    const imageBox = await image.boundingBox();
    const nameBox = await name.boundingBox();
    const actionCountBox = await actionCount.boundingBox();
    expect(cardBox).not.toBeNull();
    expect(imageBox).not.toBeNull();
    expect(nameBox).not.toBeNull();
    expect(actionCountBox).not.toBeNull();
    expect(cardBox!.height).toBeLessThanOrEqual(240);
    expect(Math.abs(imageBox!.x - cardBox!.x)).toBeLessThanOrEqual(2);
    expect(Math.abs(imageBox!.y - cardBox!.y)).toBeLessThanOrEqual(2);
    expect(Math.abs(imageBox!.width - cardBox!.width)).toBeLessThanOrEqual(3);
    expect(Math.abs(imageBox!.height - cardBox!.height)).toBeLessThanOrEqual(3);
    expect(nameBox!.y).toBeGreaterThanOrEqual(cardBox!.y);
    expect(actionCountBox!.y + actionCountBox!.height).toBeLessThanOrEqual(cardBox!.y + cardBox!.height);
    await expect(card.getByRole("group", { name: "陪伴 形象与动作层叠浏览" })).toHaveCount(0);
    await expect(moreButton).toBeVisible();
    await expect(card.getByRole("link", { name: "与 陪伴 对话" })).toBeHidden();
    await expect(card.getByRole("link", { name: "为 陪伴 创建动作" })).toBeHidden();

    await moreButton.click();
    await expect(card.getByRole("link", { name: "与 陪伴 对话" })).toBeVisible();
    await expect(card.getByRole("link", { name: "为 陪伴 创建动作" })).toBeVisible();
    await expect(card.getByRole("button", { name: "删除形象：陪伴" })).toBeVisible();
  });

  test("auto-plays actions while an internal Avatar card remains collapsed", async ({ page }) => {
    await page.goto("/avatars?scope=internal-preset");

    const card = page.getByRole("article").filter({ has: page.getByRole("heading", { name: "陪伴" }) });
    await expect(card).toHaveAttribute("data-expanded", "false");
    await expect(card.getByRole("group", { name: "陪伴 形象与动作层叠浏览" })).toHaveCount(0);
    await expect(card.locator("video")).toHaveCount(0);
    await expect.poll(() => card.locator("video[autoplay]").count(), { timeout: 5_000 }).toBe(1);

    const actionPreview = card.locator("video[autoplay]");
    await expect(actionPreview).toBeVisible();
    await expect.poll(() => actionPreview.evaluate((video) => !(video as HTMLVideoElement).paused)).toBe(true);
    const cardBox = await card.boundingBox();
    const videoBox = await actionPreview.boundingBox();
    expect(cardBox).not.toBeNull();
    expect(videoBox).not.toBeNull();
    expect(Math.abs(videoBox!.x - cardBox!.x)).toBeLessThanOrEqual(2);
    expect(Math.abs(videoBox!.y - cardBox!.y)).toBeLessThanOrEqual(2);
    expect(Math.abs(videoBox!.width - cardBox!.width)).toBeLessThanOrEqual(3);
    expect(Math.abs(videoBox!.height - cardBox!.height)).toBeLessThanOrEqual(3);
    await expect(card.getByText(/^动作 · /)).toBeVisible();
    await expect(card).toHaveAttribute("data-expanded", "false");
  });

  test("keeps layered media controls separate from the Avatar detail link", async ({ page }) => {
    await page.route("**/api/avatars/companion", async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          avatar: {
            avatar_id: "companion",
            display_name: "陪伴",
            source_image_url: "/digital-human/opentalking/companion/reference.png",
            created_at: "2026-08-29T00:00:00.000Z",
            updated_at: "2026-08-29T00:00:00.000Z",
            deleted_at: null,
            actions: [],
            realtime_binding: null,
          },
        }),
      });
    });
    await page.goto("/avatars");
    await page.getByRole("button", { name: /内部预制形象/ }).click();

    const card = page.getByRole("article").filter({ has: page.getByRole("heading", { name: "陪伴" }) });
    await card.getByRole("button", { name: /管理 陪伴 的 \d+ 个动作/ }).click();
    await expect(page).toHaveURL(/\/avatars\?scope=internal-preset$/);

    await card.getByRole("link", { name: "打开 陪伴 详情" }).click();
    await expect(page).toHaveURL(/\/avatars\/companion\?return_scope=internal-preset$/);
    await expect(page.getByRole("heading", { name: "陪伴" })).toBeVisible();

    await page.getByRole("link", { name: "返回资产管理" }).click();
    await expect(page).toHaveURL(/\/avatars\?scope=internal-preset$/);
    await expect(page.getByRole("button", { name: /内部预制形象/ })).toHaveAttribute("data-active", "true");
    await expect(page.getByRole("heading", { name: "陪伴" })).toBeVisible();
  });

  test("uses one immersive media stage for an Avatar image and its actions", async ({ page }) => {
    await page.addInitScript(() => {
      window.localStorage.setItem("openrealtime-motion-asset-metadata-v1", JSON.stringify({
        version: 1,
        displayNames: {},
        hiddenIds: ["builtin:opentalking:companion"],
        hiddenIdentityIds: [],
      }));
    });
    await page.route(/\/api\/avatars$/, async (route) => {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ avatars: [] }) });
    });
    await page.route("**/api/avatars/companion", async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          avatar: {
            avatar_id: "companion",
            display_name: "陪伴",
            source_image_url: "/digital-human/opentalking/companion/reference.png",
            created_at: "2026-08-29T00:00:00.000Z",
            updated_at: "2026-08-29T00:00:00.000Z",
            deleted_at: null,
            realtime_binding: null,
            actions: [
              {
                avatar_action_id: "action-smile",
                display_name: "亲和微笑",
                video_url: "/digital-human/opentalking/video-call/motion.mp4",
                pending_model_count: 0,
                created_at: "2026-08-29T00:00:00.000Z",
                deleted_at: null,
              },
              {
                avatar_action_id: "action-idle",
                display_name: "自然待机",
                video_url: "/digital-human/opentalking/video-call/motion.mp4",
                pending_model_count: 1,
                created_at: "2026-08-29T00:00:00.000Z",
                deleted_at: null,
              },
            ],
          },
        }),
      });
    });

    await page.goto("/avatars/companion");

    const stage = page.getByRole("region", { name: "陪伴 媒体舞台" });
    const dock = stage.getByRole("group", { name: "形象和动作切换" });
    await expect(stage).toBeVisible();
    await expect(dock.getByRole("button", { name: "查看形象：陪伴" })).toHaveAttribute("aria-current", "true");
    await expect(dock.getByRole("button", { name: "查看动作：亲和微笑" })).toBeVisible();
    await expect(dock.getByRole("button", { name: "查看动作：自然待机" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "动作资产" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "可直接使用图片对话" })).toHaveCount(0);

    const imageButtonBox = await dock.getByRole("button", { name: "查看形象：陪伴" }).boundingBox();
    const actionButtonBox = await dock.getByRole("button", { name: "查看动作：亲和微笑" }).boundingBox();
    expect(imageButtonBox).not.toBeNull();
    expect(actionButtonBox).not.toBeNull();
    expect(actionButtonBox!.x).toBeLessThan(imageButtonBox!.x + imageButtonBox!.width);

    await expect.poll(
      () => dock.locator('[aria-current="true"]').getAttribute("aria-label"),
      { timeout: 5_000 },
    ).toBe("查看动作：亲和微笑");

    await dock.getByRole("button", { name: "查看动作：亲和微笑" }).click();
    const activeVideo = stage.locator('video[aria-label="陪伴 · 亲和微笑"]');
    await expect(activeVideo).toBeVisible();
    await expect.poll(() => activeVideo.evaluate((video) => !(video as HTMLVideoElement).paused)).toBe(true);
    await expect.poll(() => activeVideo.evaluate((video) => getComputedStyle(video).objectFit)).toBe("contain");
    await expect(stage.getByRole("link", { name: "开始对话", exact: true })).toHaveAttribute(
      "href",
      "/conversation?avatar_id=companion&avatar_action_id=action-smile&experience=avatar",
    );
    await expect(stage.getByText("使用亲和微笑开始对话", { exact: true })).toHaveCount(0);
    await expect(page.getByText("技术信息")).toBeVisible();
  });

  test("uses the managed Avatar action catalog on the internal preset detail", async ({ page }) => {
    const shuchang = {
      avatar_id: "shuchang",
      display_name: "傻妞",
      source_image_url: "/api/avatars/shuchang/image",
      created_at: "2026-08-29T00:00:00.000Z",
      updated_at: "2026-08-31T00:00:00.000Z",
      deleted_at: null,
      realtime_binding: null,
      actions: [{
        avatar_action_id: "trashed-smile",
        display_name: "已回收微笑",
        video_url: "/trashed-smile.mp4",
        pending_model_count: 0,
        created_at: "2026-08-30T00:00:00.000Z",
        deleted_at: "2026-08-31T00:00:00.000Z",
      }],
    };
    let legacyActionCatalogRequests = 0;
    await page.route("**/api/avatars/shuchang", async (route) => {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ avatar: shuchang }) });
    });
    await page.route("**/api/avatars", async (route) => {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ avatars: [shuchang] }) });
    });
    await page.route("**/api/anam/avatars", async (route) => {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ avatars: [] }) });
    });
    await page.route("**/api/avatar-assets/actions", async (route) => {
      legacyActionCatalogRequests += 1;
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ actions: [], selection: null }) });
    });

    await page.goto("/avatars/shuchang?return_scope=internal-preset");

    const stage = page.getByRole("region", { name: "傻妞 媒体舞台" });
    await expect(stage.getByRole("button", { name: "查看动作：实时待机" })).toBeVisible();
    await expect(stage.getByText("1 个动作", { exact: true })).toBeVisible();
    await expect(page.getByText("已回收微笑", { exact: true })).toHaveCount(0);
    expect(legacyActionCatalogRequests).toBe(0);
  });

  test("keeps the current detail media visible until the next action can play", async ({ page }) => {
    await page.clock.install();
    let releaseSlowVideo = () => {};
    const slowVideoGate = new Promise<void>((resolveGate) => { releaseSlowVideo = resolveGate; });
    await page.route("**/api/avatars/companion", async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          avatar: {
            avatar_id: "companion",
            display_name: "陪伴",
            source_image_url: "/digital-human/opentalking/companion/reference.png",
            created_at: "2026-08-29T00:00:00.000Z",
            updated_at: "2026-08-29T00:00:00.000Z",
            deleted_at: null,
            realtime_binding: null,
            actions: [
              {
                avatar_action_id: "fast-action",
                display_name: "快速动作",
                video_url: "/digital-human/opentalking/video-call/motion.mp4",
                pending_model_count: 0,
                created_at: "2026-08-29T00:00:00.000Z",
                deleted_at: null,
              },
              {
                avatar_action_id: "slow-action",
                display_name: "缓慢加载动作",
                video_url: "/api/avatar-assets/artifacts/slow-action",
                pending_model_count: 0,
                created_at: "2026-08-29T00:00:00.000Z",
                deleted_at: null,
              },
            ],
          },
        }),
      });
    });
    await page.route("**/api/avatar-assets/artifacts/slow-action", async (route) => {
      await slowVideoGate;
      await route.fulfill({
        contentType: "video/mp4",
        path: resolve("public/digital-human/opentalking/video-call/motion.mp4"),
      });
    });

    await page.goto("/avatars/companion", { waitUntil: "domcontentloaded" });

    const dock = page.getByRole("group", { name: "形象和动作切换" });
    const slowAction = dock.getByRole("button", { name: "查看动作：缓慢加载动作" });
    await slowAction.click();
    await page.clock.fastForward(3_100);
    await expect(slowAction).toHaveAttribute("aria-current", "true");
    releaseSlowVideo();
  });

  test("expands an internal Avatar into layered image and action management", async ({ page }) => {
    await page.route("**/api/avatars", async (route) => {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ avatars: [] }) });
    });
    await page.route("**/api/avatar-assets/artifacts/companion-*-preview", async (route) => {
      await route.fulfill({
        path: resolve("public/digital-human/opentalking/video-call/motion.mp4"),
        contentType: "video/mp4",
      });
    });
    await page.route("**/api/avatar-assets/actions", async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          actions: [
            {
              avatar_action_id: "companion-wave",
              avatar_id: "companion",
              candidate_id: "candidate-wave",
              phase: "ready",
              source_master_artifact_id: "companion-wave-master",
              source_media: { duration_ms: 10_000, width: 1280, height: 720, video_codec: "h264", has_audio: false },
              renditions: [{
                rendition_id: "companion-wave-desktop",
                profile: "desktop_fullscreen",
                phase: "approved",
                artifact_id: "companion-wave-preview",
              }],
            },
            {
              avatar_action_id: "companion-listen",
              avatar_id: "companion",
              candidate_id: "candidate-listen",
              phase: "ready",
              source_master_artifact_id: "companion-listen-master",
              source_media: { duration_ms: 10_000, width: 1280, height: 720, video_codec: "h264", has_audio: false },
              renditions: [{
                rendition_id: "companion-listen-desktop",
                profile: "desktop_fullscreen",
                phase: "approved",
                artifact_id: "companion-listen-preview",
              }],
            },
          ],
          selection: null,
        }),
      });
    });
    await page.goto("/avatars");
    await page.getByRole("button", { name: /内部预制形象/ }).click();

    const card = page.getByRole("article").filter({ has: page.getByRole("heading", { name: "陪伴" }) });
    await expect(card.getByRole("button", { name: "管理 陪伴 的 3 个动作" })).toBeVisible();
    await expect(card.getByRole("group", { name: "陪伴 形象与动作层叠浏览" })).toHaveCount(0);
    await card.getByRole("button", { name: "管理 陪伴 的 3 个动作" }).click();
    await expect(card).toHaveAttribute("data-expanded", "true");

    const layerBrowser = card.getByRole("group", { name: "陪伴 形象与动作层叠浏览" });
    await expect(layerBrowser).toBeVisible();
    await expect(layerBrowser.getByRole("button", { name: "预览 陪伴 形象" })).toHaveAttribute("aria-current", "true");
    await expect(layerBrowser.getByRole("button", { name: /预览动作：/ })).toHaveCount(3);
    await expect.poll(
      () => layerBrowser.locator('[aria-current="true"]').getAttribute("aria-label"),
      { timeout: 5_000 },
    ).toMatch(/^预览动作：/);
    const actionPreview = layerBrowser.locator('video[data-playing="true"]');
    await expect(actionPreview).toHaveCount(1);
    await expect(actionPreview).toBeVisible();
    await expect(actionPreview).toHaveJSProperty("autoplay", true);
    await expect(actionPreview).toHaveJSProperty("muted", true);
    await expect.poll(() => actionPreview.evaluate((video) => !(video as HTMLVideoElement).paused)).toBe(true);
    await expect(card.getByRole("button", { name: /删除动作：/ })).toHaveAttribute("title", "删除动作");
    const firstCurrentLabel = await layerBrowser.locator('[aria-current="true"]').getAttribute("aria-label");
    await page.mouse.move(0, 0);
    await expect.poll(() => layerBrowser.locator('[aria-current="true"]').getAttribute("aria-label"), { timeout: 5_000 }).not.toBe(firstCurrentLabel);

    await card.getByRole("button", { name: /放大预览：/ }).click();
    const dialog = page.getByRole("dialog", { name: /动作预览/ });
    await expect(dialog).toBeVisible();
    const enlargedPreview = dialog.locator("video[controls]");
    await expect(enlargedPreview).toBeVisible();
    await expect(enlargedPreview).toHaveJSProperty("loop", true);
    await expect(dialog.getByText(/自动循环播放/)).toBeVisible();
    await dialog.getByRole("button", { name: "关闭动作预览" }).click();
    await expect(dialog).toHaveCount(0);

    const shuchangCard = page.getByRole("article").filter({ has: page.getByRole("heading", { name: "Shuchang" }) });
    await expect(shuchangCard.getByRole("button", { name: /管理 Shuchang 的/ })).toHaveCount(0);
    await card.getByRole("button", { name: "收起 陪伴 的形象和动作" }).click();
    await expect(card).toHaveAttribute("data-expanded", "false");
    await expect(card.locator("video[autoplay]")).toHaveCount(1);
  });

  test("merges newly created actions into the canonical internal preset card", async ({ page }) => {
    await page.route("**/api/avatars", async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          avatars: [{
            avatar_id: "companion",
            display_name: "陪伴",
            source_image_url: "/api/avatars/companion/image",
            created_at: "2026-08-29T00:00:00.000Z",
            updated_at: "2026-08-29T00:00:00.000Z",
            deleted_at: null,
            realtime_binding: null,
            actions: [{
              avatar_action_id: "action-smile",
              display_name: "亲和微笑",
              video_url: "/api/avatar-assets/artifacts/smile-preview",
              pending_model_count: 0,
              created_at: "2026-08-29T00:00:00.000Z",
              deleted_at: null,
            }],
          }],
        }),
      });
    });
    await page.route("**/api/avatar-assets/actions", async (route) => {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ actions: [], selection: null }) });
    });
    await page.route("**/api/anam/avatars", async (route) => {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ avatars: [] }) });
    });

    await page.goto("/avatars");
    await page.getByRole("button", { name: /内部预制形象/ }).click();

    await expect(page.getByRole("article")).toHaveCount(2);
    const companion = page.getByRole("article").filter({ has: page.getByRole("heading", { name: "陪伴" }) });
    await expect(companion.getByText("2 个动作", { exact: true })).toBeVisible();
  });

  test("deletes an internal action independently and removes a deleted preset across reloads", async ({ page }) => {
    await page.route("**/api/avatar-assets/actions", async (route) => {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ actions: [], selection: null }) });
    });

    await page.goto("/avatars");
    await page.locator("button").nth(1).click();

    let card = page.getByRole("article").filter({ has: page.getByRole("heading", { name: "陪伴" }) });
    await card.getByRole("button", { name: "管理 陪伴 的 1 个动作" }).click();
    await card.getByRole("button", { name: "预览动作：陪伴 · 内置动作" }).click();
    await card.getByRole("button", { name: "删除动作：陪伴 · 内置动作" }).click();
    let dialog = page.getByRole("dialog", { name: "删除数字人动作？" });
    await expect(dialog).toContainText("数字人形象和其他动作不受影响");
    await dialog.getByRole("button", { name: "确认删除" }).click();
    await expect(card.getByText("未创建动作", { exact: true })).toBeVisible();

    await page.reload();
    await page.locator("button").nth(1).click();
    card = page.getByRole("article").filter({ has: page.getByRole("heading", { name: "陪伴" }) });
    await expect(card.getByText("未创建动作", { exact: true })).toBeVisible();

    await card.getByRole("button", { name: "更多操作：陪伴" }).click();
    await card.getByRole("button", { name: "删除形象：陪伴" }).click();
    dialog = page.getByRole("dialog", { name: "删除数字人形象？" });
    await expect(dialog).toContainText("这个形象及其动作会从内部预置资产中移除");
    await dialog.getByRole("button", { name: "确认删除" }).click();
    await expect(page.getByRole("heading", { name: "陪伴" })).toHaveCount(0);

    await page.reload();
    await page.locator("button").nth(1).click();
    await expect(page.getByRole("heading", { name: "陪伴" })).toHaveCount(0);
    await expect(page.getByRole("article")).toHaveCount(1);
  });

  test("separates custom realtime Avatars from provider built-ins", async ({ page }) => {
    await page.route("**/api/anam/avatars", async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          avatars: [
            { id: "my-avatar", displayName: "我的数字人", origin: "personal", activeVersion: "cara-4", imageUrl: "/mine.png" },
            { id: "stock-avatar", displayName: "官方数字人", origin: "official", activeVersion: "cara-4", imageUrl: "/stock.png" },
          ],
        }),
      });
    });

    await page.goto("/avatars");

    await expect(page.getByRole("button", { name: /自定义 Avatar 1/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /官方内置 Avatar 1/ })).toBeVisible();
    await expect(page.getByRole("heading", { name: "我的数字人" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "官方数字人" })).toHaveCount(0);

    await page.getByRole("button", { name: /官方内置 Avatar/ }).click();
    await expect(page.getByRole("heading", { name: "官方数字人" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "我的数字人" })).toHaveCount(0);
  });

  test("opens provider built-in Avatar details from its card", async ({ page }) => {
    await page.route("**/api/anam/avatars", async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          avatars: [{
            id: "stock-avatar",
            displayName: "官方数字人",
            origin: "official",
            activeVersion: "cara-4",
            imageUrl: "/stock.png",
            videoUrl: "/stock.mp4",
          }],
        }),
      });
    });

    await page.goto("/avatars");
    await page.getByRole("button", { name: /官方内置 Avatar/ }).click();
    const card = page.getByRole("article").filter({ has: page.getByRole("heading", { name: "官方数字人" }) });
    await card.getByRole("button", { name: "更多操作：官方数字人" }).click();
    await card.getByRole("link", { name: "打开 官方数字人 详情" }).click();

    await expect(page).toHaveURL(/\/avatars\/anam-stock-avatar\?return_scope=realtime&return_realtime_scope=built-in$/);
    await expect(page.getByRole("heading", { name: "官方数字人" })).toBeVisible();
    await expect(page.getByText("Anam 实时", { exact: true })).toBeVisible();

    await page.getByRole("link", { name: "返回资产管理" }).click();
    await expect(page).toHaveURL(/\/avatars\?scope=realtime&realtime_scope=built-in$/);
    await expect(page.getByRole("button", { name: /实时驱动数字人/ })).toHaveAttribute("data-active", "true");
    await expect(page.getByRole("button", { name: /官方内置 Avatar/ })).toHaveAttribute("data-active", "true");
    await expect(page.getByRole("heading", { name: "官方数字人" })).toBeVisible();
  });

  test("lets users scroll through more than the first row of built-in Avatars", async ({ page }) => {
    await page.route("**/api/anam/avatars", async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          avatars: ["Mia", "Liv", "Gabriel", "Anne", "Bella", "Finn"].map((displayName, index) => ({
            id: `anam-${index}`,
            displayName,
            origin: "official",
            activeVersion: "cara-4",
            imageUrl: `/${displayName.toLowerCase()}.png`,
          })),
        }),
      });
    });

    await page.goto("/avatars");
    await page.getByRole("button", { name: /实时驱动数字人/ }).click();
    await page.getByRole("button", { name: /官方内置 Avatar/ }).click();

    const lastAvatar = page.getByRole("heading", { name: "Finn" });
    await page.getByRole("heading", { name: "Mia" }).hover();
    await page.mouse.wheel(0, 1800);
    await expect(lastAvatar).toBeInViewport();
  });

  test("connects the two primary destinations through the shared shell", async ({ page }) => {
    await page.goto("/avatars");

    await expect(page.getByRole("heading", { name: "数字人资产" })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Avatar 页面" })).toContainText("资产管理");
    await page.getByRole("link", { name: "创建数字人" }).first().click();
    await expect(page).toHaveURL(/\/avatars\/create$/);
    await expect(page.getByRole("banner").getByRole("heading", { name: "创建数字人" })).toBeVisible();
  });

  test("keeps the creation task, source buttons, and next action in the first viewport", async ({ page }) => {
    await page.goto("/avatars/create");

    await expect(page.locator("main h1")).toHaveCount(0);
    const taskSwitch = page.getByLabel("创建任务");
    const realtimeTask = taskSwitch.getByRole("button", { name: /创建实时驱动 Avatar/ });
    await expect(realtimeTask).toBeVisible();
    await expect(page.getByRole("region", { name: "当前任务流程" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "选择 Avatar 形象" })).toBeInViewport();
    await expect(page.getByRole("group", { name: "形象来源" })).toBeInViewport();

    const taskBox = await realtimeTask.boundingBox();
    expect(taskBox).not.toBeNull();
    expect(taskBox!.height).toBeLessThanOrEqual(64);

    await page.getByRole("group", { name: "内部预制形象" }).getByRole("button", { name: "陪伴" }).click();
    await expect(page.getByRole("button", { name: "确认 Avatar 并创建实时驱动" })).toBeInViewport();
  });

  test("keeps a compact sidebar at medium widths and uses a mobile configuration drawer", async ({ page }) => {
    const avatar = {
      avatar_id: "companion",
      display_name: "陪伴",
      source_image_url: "/digital-human/opentalking/companion/reference.png",
      created_at: "2026-08-30T00:00:00.000Z",
      updated_at: "2026-08-30T00:00:00.000Z",
      deleted_at: null,
      actions: [],
      realtime_binding: null,
    };
    await page.route("**/api/avatars", async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ avatar }) });
    });
    await page.setViewportSize({ width: 850, height: 1000 });
    await page.goto("/avatars/create?task=action");

    const sourceSidebar = page.getByRole("heading", { name: "选择 Avatar 形象" }).locator("..").locator("..");
    const visualWorkspace = page.getByRole("region", { name: "Avatar 视觉工作区" });
    const sidebarBox = await sourceSidebar.boundingBox();
    const visualBox = await visualWorkspace.boundingBox();
    expect(sidebarBox).not.toBeNull();
    expect(visualBox).not.toBeNull();
    expect(sidebarBox!.x).toBeLessThan(visualBox!.x);
    expect(sidebarBox!.width).toBeLessThan(visualBox!.width);
    await expect(page.getByRole("button", { name: "配置 Avatar" })).toBeHidden();

    await page.getByRole("group", { name: "内部预制形象" }).getByRole("button", { name: "陪伴" }).click();
    await page.getByRole("button", { name: "确认 Avatar 并创建动作" }).click();
    const actionControls = page.getByRole("heading", { name: "动作创作" });
    const actionPreview = page.getByText("效果确认", { exact: true });
    const actionControlsBox = await actionControls.boundingBox();
    const actionPreviewBox = await actionPreview.boundingBox();
    expect(actionControlsBox).not.toBeNull();
    expect(actionPreviewBox).not.toBeNull();
    expect(actionPreviewBox!.x).toBeGreaterThan(actionControlsBox!.x + 250);
    expect(actionPreviewBox!.y).toBeLessThan(actionControlsBox!.y + 150);

    await page.setViewportSize({ width: 390, height: 844 });
    const drawerToggle = page.getByRole("button", { name: "动作配置" });
    await expect(drawerToggle).toBeVisible();
    await expect(actionControls).not.toBeInViewport();
    await drawerToggle.click();
    await expect(actionControls).toBeInViewport();
    await expect(page.getByRole("button", { name: "收起配置" })).toHaveAttribute("aria-expanded", "true");
    await page.keyboard.press("Escape");
    await expect(actionControls).not.toBeInViewport();
  });

  test("uses a centered Avatar gallery with compact confirmation controls", async ({ page }) => {
    await page.addInitScript(() => {
      window.localStorage.setItem("openrealtime-avatar-identity-display-names", JSON.stringify({
        shuchang: "傻妞",
      }));
    });
    await page.goto("/avatars/create");

    const sourceModes = page.getByRole("group", { name: "形象来源" });
    await expect(sourceModes.getByRole("button")).toHaveCount(3);
    await expect(sourceModes.getByRole("button", { name: "从资产库选择" })).toBeVisible();
    await expect(sourceModes.getByRole("button", { name: "上传图片" })).toBeVisible();
    await expect(sourceModes.getByRole("button", { name: "创建图片" })).toBeVisible();
    await expect(sourceModes.getByRole("button", { name: "HappyImage 创作" })).toHaveCount(0);
    await expect(page.getByRole("complementary", { name: "Avatar 预览" })).toHaveCount(0);

    const confirm = page.getByRole("button", { name: "确认 Avatar 并创建实时驱动" });
    await expect(confirm).toBeDisabled();
    const gallery = page.getByRole("group", { name: "内部预制形象" });
    const firstAvatar = gallery.getByRole("button", { name: "傻妞" });
    const companion = gallery.getByRole("button", { name: "陪伴" });
    await companion.click();
    await expect(confirm).toBeEnabled();
    await expect(companion).toHaveAttribute("aria-current", "true");
    await expect(page.getByRole("textbox", { name: "Avatar 名称" })).toHaveValue("陪伴");
    await expect(page.getByText("当前选择", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "上一个 Avatar" })).toBeVisible();
    await expect(page.getByRole("button", { name: "下一个 Avatar" })).toBeVisible();

    await expect.poll(async () => {
      const firstBox = await firstAvatar.boundingBox();
      const companionBox = await companion.boundingBox();
      return firstBox && companionBox ? companionBox.width - firstBox.width : 0;
    }).toBeGreaterThan(0);

    await companion.click();
    await expect(page.getByRole("dialog", { name: "陪伴 大图预览" })).toBeVisible();
    await page.keyboard.press("Escape");

    await page.getByRole("button", { name: "上一个 Avatar" }).click();
    await expect(firstAvatar).toHaveAttribute("aria-current", "true");
    await expect(page.getByRole("textbox", { name: "Avatar 名称" })).toHaveValue("傻妞");
    await expect(page.getByRole("heading", { name: "确认 Avatar" })).toHaveCount(0);
  });

  test("confirms the selected Avatar and enters action creation without an intermediate page", async ({ page }) => {
    const avatar = {
      avatar_id: "companion",
      display_name: "陪伴",
      source_image_url: "/digital-human/opentalking/companion/reference.png",
      created_at: "2026-08-30T00:00:00.000Z",
      updated_at: "2026-08-30T00:00:00.000Z",
      deleted_at: null,
      actions: [],
      realtime_binding: null,
    };
    await page.route("**/api/avatars", async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ avatar }) });
    });

    await page.goto("/avatars/create");
    await page.getByRole("button", { name: /创建 Avatar 动作/ }).click();
    await page.getByRole("group", { name: "内部预制形象" }).getByRole("button", { name: "陪伴" }).click();

    await expect(page.getByRole("textbox", { name: "Avatar 名称" })).toHaveValue("陪伴");
    await expect(page.getByRole("heading", { name: "确认 Avatar" })).toHaveCount(0);
    await page.getByRole("button", { name: "确认 Avatar 并创建动作" }).click();
    await expect(page.getByRole("heading", { name: "动作创作" })).toBeVisible();
  });

  test("opens the selected Avatar image in a large modal preview", async ({ page }) => {
    await page.goto("/avatars/create");
    await page.getByRole("group", { name: "内部预制形象" }).getByRole("button", { name: "陪伴" }).click();

    await page.getByRole("button", { name: "预览 陪伴" }).click();
    const dialog = page.getByRole("dialog", { name: "陪伴 大图预览" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("img", { name: "陪伴 完整预览" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
  });

  test("moves backward and forward across Avatar selection, task creation, and completion", async ({ page }) => {
    const baseAvatar = {
      avatar_id: "companion",
      display_name: "陪伴",
      source_image_url: "/digital-human/opentalking/companion/reference.png",
      created_at: "2026-08-30T00:00:00.000Z",
      updated_at: "2026-08-30T00:00:00.000Z",
      deleted_at: null,
      actions: [],
      realtime_binding: null,
    };
    await page.route("**/api/avatars**", async (route) => {
      const url = new URL(route.request().url());
      if (route.request().method() === "GET" && url.pathname === "/api/avatars") {
        await route.fulfill({ contentType: "application/json", body: JSON.stringify({ avatars: [] }) });
        return;
      }
      if (route.request().method() === "POST" && url.pathname === "/api/avatars") {
        await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ avatar: baseAvatar }) });
        return;
      }
      if (route.request().method() === "PATCH" && url.pathname === "/api/avatars/companion") {
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify({ avatar: {
            ...baseAvatar,
            realtime_binding: {
              avatar_id: "companion",
              provider: "anam",
              provider_avatar_id: "anam-companion",
              avatar_model: "cara-4",
              state: "accepted",
              preview_video_url: null,
            },
          } }),
        });
        return;
      }
      await route.continue();
    });
    await page.route("**/api/anam/avatars", async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ avatar: {
          id: "anam-companion",
          displayName: "陪伴数字人",
          activeVersion: "cara-4",
          videoUrl: null,
        } }),
      });
    });

    await page.goto("/avatars/create");
    await page.getByRole("group", { name: "内部预制形象" }).getByRole("button", { name: "陪伴" }).click();
    await page.getByRole("button", { name: "确认 Avatar 并创建实时驱动" }).click();
    await expect(page.getByRole("heading", { name: "创建实时驱动 Avatar" })).toBeVisible();

    await page.getByRole("button", { name: "上一步：选择 Avatar" }).click();
    await expect(page.getByRole("heading", { name: "选择 Avatar 形象" })).toBeVisible();
    await page.getByRole("button", { name: "确认 Avatar 并创建实时驱动" }).click();
    await page.getByRole("button", { name: "创建实时驱动形象", exact: true }).click();
    await page.getByRole("button", { name: "确认效果并启用" }).click();

    await expect(page.getByRole("heading", { name: "实时驱动已启用" })).toBeVisible();
    await page.getByRole("button", { name: "上一步", exact: true }).click();
    await expect(page.getByText("实时驱动已确认并绑定")).toBeVisible();
  });

  test("shows the task switch above one shared Avatar selector", async ({ page }) => {
    await page.goto("/avatars/create");

    await expect(page.getByRole("button", { name: /创建实时驱动 Avatar/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /创建 Avatar 动作/ })).toBeVisible();
    await expect(page.getByRole("heading", { name: "选择 Avatar 形象" })).toHaveCount(1);
    const realtimeTask = page.getByRole("button", { name: /创建实时驱动 Avatar/ });
    const actionTask = page.getByRole("button", { name: /创建 Avatar 动作/ });
    await expect(realtimeTask).toHaveAttribute("data-active", "true");
    await expect(actionTask).toHaveAttribute("data-active", "false");
    await expect(page.getByRole("region", { name: "当前任务流程" })).toHaveCount(0);

    await actionTask.click();
    await expect(realtimeTask).toHaveAttribute("data-active", "false");
    await expect(actionTask).toHaveAttribute("data-active", "true");
    await expect(page.getByRole("tab", { name: "从资产库选择" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "从资产库选择" })).toBeVisible();
    await page.getByRole("group", { name: "内部预制形象" }).getByRole("button", { name: "陪伴" }).click();
    await expect(page.getByRole("button", { name: "确认 Avatar 并创建动作" })).toBeVisible();
  });

  test("uses the same two internal presets in Avatar creation", async ({ page }) => {
    await page.addInitScript(() => {
      window.localStorage.setItem("openrealtime-avatar-identity-display-names", JSON.stringify({
        shuchang: "傻妞",
        "office-woman": "职场女",
      }));
    });
    await page.route("**/api/avatars", async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      expect(route.request().postDataJSON()).toMatchObject({
        avatarId: "companion",
        displayName: "陪伴",
      });
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          avatar: {
            avatar_id: "companion",
            display_name: "陪伴",
            source_image_url: "/digital-human/opentalking/companion/reference.png",
            owner_id: "local-user",
            visibility: "private",
            created_at: "2026-08-29T00:00:00.000Z",
            updated_at: "2026-08-29T00:00:00.000Z",
            deleted_at: null,
            actions: [],
            realtime_binding: null,
          },
        }),
      });
    });

    await page.goto("/avatars/create");

    const presets = page.getByRole("group", { name: "内部预制形象" });
    await expect(presets.getByRole("button")).toHaveCount(2);
    await expect(presets.getByRole("button", { name: "傻妞" })).toBeVisible();
    await expect(presets.getByRole("button", { name: "陪伴" })).toBeVisible();

    await presets.getByRole("button", { name: "傻妞" }).click();
    const nameInput = page.getByRole("textbox", { name: "Avatar 名称" });
    await expect(nameInput).toHaveAttribute("maxlength", "50");
    await expect(nameInput).toHaveValue("傻妞");
    await presets.getByRole("button", { name: "陪伴" }).click();
    await expect(nameInput).toHaveValue("陪伴");
    await expect(page.getByRole("button", { name: "确认 Avatar 并创建实时驱动" })).toBeEnabled();
    await page.getByRole("button", { name: "确认 Avatar 并创建实时驱动" }).click();

    const selectedAvatar = page.getByLabel("当前共享 Avatar");
    const selectedAvatarBox = await selectedAvatar.boundingBox();
    const realtimePreviewBox = await page.getByRole("region", { name: "实时驱动效果预览" }).boundingBox();
    expect(selectedAvatarBox).not.toBeNull();
    expect(realtimePreviewBox).not.toBeNull();
    expect(selectedAvatarBox!.x).toBeLessThan(realtimePreviewBox!.x);
    expect(selectedAvatarBox!.width).toBeLessThan(realtimePreviewBox!.width);

    const anamNameInput = page.getByRole("textbox", { name: "Anam 形象名称" });
    await expect(anamNameInput).toHaveValue("陪伴数字人");
    await expect(anamNameInput).toHaveAttribute("minlength", "3");
    await expect(anamNameInput).toHaveAttribute("maxlength", "50");
    await expect(page.getByRole("button", { name: "创建实时驱动形象", exact: true })).toBeEnabled();
    await expect(page.getByLabel("当前共享 Avatar")).toContainText("companion");
    await expect(page.getByRole("region", { name: "创建实时驱动 Avatar" })).toHaveAttribute("data-transition", "in-page");
    await expect(page.locator("h1")).toHaveCount(1);
    await anamNameInput.fill("陪伴");
    await expect(page.getByRole("button", { name: "创建实时驱动形象", exact: true })).toBeDisabled();
  });

  test("suggests the next numbered name for an uploaded Avatar when the name is left blank", async ({ page }) => {
    let submittedName = "";
    await page.route("**/api/avatars", async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify({ avatars: [{
            avatar_id: "avatar-existing",
            display_name: "数字人1",
            source_image_url: "/api/avatars/avatar-existing/image",
            created_at: "2026-08-29T00:00:00.000Z",
            updated_at: "2026-08-29T00:00:00.000Z",
            deleted_at: null,
            actions: [],
            realtime_binding: null,
          }] }),
        });
        return;
      }
      submittedName = route.request().postDataJSON().displayName;
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          avatar: {
            avatar_id: "avatar-created",
            display_name: submittedName,
            source_image_url: "/api/avatars/avatar-created/image",
            created_at: "2026-08-30T00:00:00.000Z",
            updated_at: "2026-08-30T00:00:00.000Z",
            deleted_at: null,
            actions: [],
            realtime_binding: null,
          },
        }),
      });
    });

    await page.goto("/avatars/create");
    await page.getByRole("button", { name: "上传图片" }).click();
    await page.locator('input[type="file"]').setInputFiles(resolve("public/digital-human/opentalking/companion/reference.png"));
    const nameInput = page.getByRole("textbox", { name: "Avatar 名称" });
    await expect(page.getByText("请填写 Avatar 名称；留空将自动使用“数字人2”")).toBeVisible();
    await expect(nameInput).toHaveAttribute("placeholder", "不填写则使用数字人2");
    await nameInput.fill("");
    const createButton = page.getByRole("button", { name: "确认 Avatar 并创建实时驱动" });
    await expect(createButton).toBeEnabled();
    await createButton.click();

    await expect.poll(() => submittedName).toBe("数字人2");
    await expect(page.getByLabel("当前共享 Avatar")).toContainText("数字人2");
  });

  test("does not reuse the HappyImage prompt as the Avatar name", async ({ page }) => {
    let submittedName = "";
    await page.route("**/api/avatars", async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({ contentType: "application/json", body: JSON.stringify({ avatars: [] }) });
        return;
      }
      submittedName = route.request().postDataJSON().displayName;
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          avatar: {
            avatar_id: "avatar-happyimage",
            display_name: submittedName,
            source_image_url: "/digital-human/opentalking/companion/reference.png",
            created_at: "2026-08-30T00:00:00.000Z",
            updated_at: "2026-08-30T00:00:00.000Z",
            deleted_at: null,
            actions: [],
            realtime_binding: null,
          },
        }),
      });
    });
    await page.route("**/api/happyimage/avatar-images", async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ imageUrl: "/digital-human/opentalking/companion/reference.png" }),
      });
    });

    await page.goto("/avatars/create");
    await page.getByRole("button", { name: "创建图片" }).click();
    await page.getByPlaceholder("描述人物外观、服装、光线与背景…").fill("未来感银色短发女性");
    await page.getByRole("button", { name: "生成形象" }).click();
    await expect(page.getByText("请填写 Avatar 名称；留空将自动使用“数字人1”")).toBeVisible();

    const nameInput = page.getByRole("textbox", { name: "Avatar 名称" });
    await expect(nameInput).toHaveValue("");
    await page.getByRole("button", { name: "确认 Avatar 并创建实时驱动" }).click();
    await expect.poll(() => submittedName).toBe("数字人1");
  });

  test("keeps the selected Avatar when entering the action task", async ({ page }) => {
    let submittedMotion = "";
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
    await page.route("**/api/avatars**", async (route) => {
      const url = new URL(route.request().url());
      if (route.request().method() === "POST" && url.pathname === "/api/avatars") {
        await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ avatar }) });
        return;
      }
      if (route.request().method() === "GET" && url.pathname === "/api/avatars/companion") {
        await route.fulfill({ contentType: "application/json", body: JSON.stringify({ avatar }) });
        return;
      }
      if (route.request().method() === "POST" && url.pathname === "/api/avatars/companion/actions") {
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({ action: {
            avatar_action_id: "action-upload-motion",
            display_name: "custom-motion",
            video_url: "/api/avatar-assets/artifacts/artifact-upload",
            pending_model_count: 1,
            created_at: "2026-08-30T00:00:00.000Z",
            deleted_at: null,
          } }),
        });
        return;
      }
      if (route.request().method() === "PATCH" && url.pathname === "/api/avatars/companion/actions/action-upload-motion") {
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify({ action: {
            avatar_action_id: "action-upload-motion",
            display_name: "custom-motion",
            video_url: "/api/avatar-assets/artifacts/artifact-upload",
            pending_model_count: 0,
            created_at: "2026-08-30T00:00:00.000Z",
            deleted_at: null,
          } }),
        });
        return;
      }
      await route.continue();
    });
    await page.route("**/api/liveportrait", async (route) => {
      if (route.request().method() === "POST") {
        submittedMotion = route.request().postDataBuffer()?.toString("latin1") ?? "";
        await route.fulfill({
          status: 202,
          contentType: "application/json",
          body: JSON.stringify({ task_id: "task-upload-motion", state: "queueing" }),
        });
        return;
      }
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ ready: true, templates: [
          { id: "sweet-vitality", available: true },
          { id: "fresh-pastoral", available: true },
          { id: "romantic-french", available: true },
          { id: "soft-glow", available: true },
          { id: "cool-night", available: true },
          { id: "gentle-intellectual", available: true },
          { id: "melancholy-empathy", available: true },
        ] }),
      });
    });
    await page.route("**/api/liveportrait/task-upload-motion", async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ state: "success", result_url: "/digital-human/opentalking/companion/action.mp4" }),
      });
    });
    await page.route("**/api/avatar-assets/candidates/provider", async (route) => {
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ candidate_id: "candidate-upload-motion" }),
      });
    });
    await page.route("**/api/avatar-assets/candidates/candidate-upload-motion/accept", async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          avatar_action_id: "action-upload-motion",
          phase: "ready",
          renditions: [{
            rendition_id: "rendition-upload-motion",
            phase: "approved",
            artifact_id: "artifact-upload",
            media: { duration_ms: 5_000 },
          }],
        }),
      });
    });
    await page.route("**/api/avatar-renderer/preparations", async (route) => {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ state: "ready", progress: 100 }) });
    });

    await page.goto("/avatars/create?task=action&avatar_id=companion");

    await expect(page.getByRole("heading", { name: "动作创作" })).toBeVisible();
    await expect(page.getByText("陪伴", { exact: true }).first()).toBeVisible();

    const actionStudio = page.getByRole("region", { name: "动作创作" });
    const previewStage = actionStudio.getByRole("complementary", { name: "动作效果预览" });
    await expect(previewStage.getByText("Step 02 / Preview")).toHaveCount(0);
    const actionPicker = actionStudio.getByRole("combobox", { name: "动作选项" });
    const actionOptions = actionStudio.getByRole("listbox", { name: "内置动作选项" });
    await expect(previewStage.getByAltText("当前形象预览：陪伴")).toBeVisible();
    await expect(previewStage.getByRole("group", { name: "切换内置动作参考" })).toHaveCount(0);
    await actionPicker.click();
    await expect(actionOptions.getByRole("option")).toHaveCount(7);
    await expect(actionOptions.getByRole("option", { name: /甜美元气/ })).not.toContainText("仅供参考");
    await actionOptions.getByRole("option", { name: /甜美元气/ }).click();
    await expect(previewStage.getByLabel("参考动作预览：甜美元气")).toHaveAttribute("src", "/digital-human/liveportrait-actions/sweet-vitality.mp4");
    await expect(actionStudio.getByRole("button", { name: "生成动作" })).toBeEnabled();
    await actionStudio.getByRole("button", { name: "生成动作" }).click();
    await expect(previewStage.getByLabel("生成效果预览：甜美元气")).toBeVisible();
    await expect(actionStudio.getByText(/含原始口型|嘴部表现/)).toHaveCount(0);
    await expect(previewStage.getByRole("checkbox")).toHaveCount(0);
    await expect(previewStage.getByRole("button", { name: "创建动作资产" })).toBeEnabled();
    await actionPicker.click();
    await actionOptions.getByRole("option", { name: /忧郁共鸣/ }).click();
    await expect(actionStudio.getByRole("textbox", { name: "动作名称" })).toHaveValue("忧郁共鸣");
    await actionStudio.getByRole("button", { name: "上传动作" }).click();
    await actionStudio.locator('input[type="file"]').setInputFiles({
      name: "custom-motion.mp4",
      mimeType: "video/mp4",
      buffer: Buffer.from("000000186674797069736f6d", "hex"),
    });
    const strength = actionStudio.getByRole("slider", { name: "动作幅度数值" });
    await expect(strength).toHaveValue("1");
    await strength.fill("1.07");
    await expect(actionStudio.getByText("1.07×", { exact: true })).toBeVisible();
    await actionStudio.getByRole("button", { name: /明显/ }).click();
    await expect(strength).toHaveValue("1.2");
    await strength.fill("1.07");
    await actionStudio.getByRole("button", { name: "生成动作" }).click();

    await expect.poll(() => submittedMotion).toContain('name="driverId"\r\n\r\nupload');
    expect(submittedMotion).toContain('name="driving"; filename="custom-motion.mp4"');
    expect(submittedMotion).toContain('"driving_multiplier":1.07');
    const actionPreview = previewStage.getByLabel("生成效果预览：custom-motion");
    await expect(actionPreview).toBeVisible();
    const previewStageBox = await previewStage.boundingBox();
    const previewFrameBox = await previewStage.locator('[data-preview-frame="true"]').boundingBox();
    const actionPreviewBox = await actionPreview.boundingBox();
    expect(previewStageBox).not.toBeNull();
    expect(previewFrameBox).not.toBeNull();
    expect(actionPreviewBox).not.toBeNull();
    expect(actionPreviewBox!.width / previewFrameBox!.width).toBeGreaterThan(0.98);
    expect(actionPreviewBox!.height / previewFrameBox!.height).toBeGreaterThan(0.98);
    await previewStage.getByRole("button", { name: "当前形象" }).click();
    await expect(previewStage.getByAltText("当前形象预览：陪伴")).toBeVisible();
    await previewStage.getByRole("button", { name: "参考动作" }).click();
    await expect(previewStage.getByLabel("参考动作预览：自定义动作")).toBeVisible();
    await previewStage.getByRole("button", { name: "生成效果" }).click();
    await expect(actionPreview).toBeVisible();
    const createActionAsset = actionStudio.getByRole("button", { name: "创建动作资产" });
    const createActionAssetBox = await createActionAsset.boundingBox();
    expect(createActionAssetBox).not.toBeNull();
    const previewCenter = previewStageBox!.x + previewStageBox!.width / 2;
    const buttonCenter = createActionAssetBox!.x + createActionAssetBox!.width / 2;
    expect(Math.abs(previewCenter - buttonCenter)).toBeLessThan(previewStageBox!.width * 0.08);
    expect(createActionAssetBox!.y).toBeGreaterThan(previewFrameBox!.y + previewFrameBox!.height * 0.5);
    await createActionAsset.click();
    await expect(actionStudio.getByRole("button", { name: "动作资产已创建" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "动作创作" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Avatar 动作已保存" })).toHaveCount(0);
    await expect(actionPreview).toBeVisible();
    await expect(actionStudio.getByText("保存后自动开始口型预处理")).toHaveCount(0);
    await expect(actionStudio.getByRole("link", { name: "查看 Avatar" })).toHaveAttribute("href", "/avatars/companion");
    await expect(actionStudio.getByRole("button", { name: "继续创建动作" })).toHaveCount(0);
  });

  test("opens action links inside the unified creation canvas", async ({ page }) => {
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
    await page.route("**/api/avatars/companion", async (route) => {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ avatar }) });
    });
    await page.route("**/api/liveportrait", async (route) => {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ ready: true, templates: [] }) });
    });

    await page.goto("/avatars/create?task=action&avatar_id=companion");

    await expect(page).toHaveURL(/\/avatars\/create\?task=action&avatar_id=companion$/);
    await expect(page.locator("h1")).toHaveCount(1);
    await expect(page.getByRole("heading", { name: "动作创作" })).toBeVisible();
    await expect(page.getByRole("region", { name: "动作创作" })).toHaveAttribute("data-transition", "in-page");
  });

  test("views video-generation prompts in a modal and preserves a custom prompt draft", async ({ page }) => {
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
    await page.route("**/api/avatars/companion", async (route) => {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ avatar }) });
    });
    await page.route("**/api/liveportrait", async (route) => {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ ready: true, templates: [] }) });
    });
    await page.route("**/api/ltx/image-to-video", async (route) => {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ ready: true }) });
    });

    await page.goto("/avatars/create?task=action&avatar_id=companion");

    const actionStudio = page.getByRole("region", { name: "动作创作" });
    await actionStudio.getByRole("tab", { name: /视频生成/ }).click();
    const promptSelect = actionStudio.getByRole("combobox", { name: "视频生成提示词选择" });
    const promptOptions = actionStudio.getByRole("listbox", { name: "视频生成提示词选项" });
    const viewPrompt = actionStudio.getByRole("button", { name: "查看当前视频生成提示词" });
    await expect(actionStudio.getByLabel("视频生成弹窗提示词内容")).toHaveCount(0);

    await viewPrompt.click();
    let promptDialog = page.getByRole("dialog", { name: "甜美元气" });
    await expect(promptDialog).toBeVisible();
    await expect(promptDialog.getByLabel("视频生成弹窗提示词内容")).toHaveAttribute("readonly", "");
    await expect(promptDialog.getByRole("button", { name: "关闭提示词弹窗" })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(promptDialog).toHaveCount(0);
    await expect(viewPrompt).toBeFocused();

    await promptSelect.click();
    await promptOptions.getByRole("option", { name: /自定义提示词/ }).click();
    await viewPrompt.click();
    promptDialog = page.getByRole("dialog", { name: "自定义提示词" });
    const promptEditor = promptDialog.getByLabel("视频生成弹窗提示词内容");
    await promptEditor.fill("A calm front-facing custom idle loop.");
    await promptDialog.getByRole("button", { name: "完成" }).click();
    await promptSelect.click();
    await promptOptions.getByRole("option", { name: /甜美元气/ }).click();
    await promptSelect.click();
    await promptOptions.getByRole("option", { name: /自定义提示词/ }).click();
    await viewPrompt.click();
    await expect(page.getByRole("dialog", { name: "自定义提示词" }).getByLabel("视频生成弹窗提示词内容"))
      .toHaveValue("A calm front-facing custom idle loop.");
  });

  test("reports a readable error when action candidate creation returns HTML", async ({ page }) => {
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
    await page.route("**/api/avatars/companion", async (route) => {
      await route.fulfill({ contentType: "application/json", body: JSON.stringify({ avatar }) });
    });
    await page.route("**/api/liveportrait", async (route) => {
      if (route.request().method() === "POST") {
        await route.fulfill({
          status: 202,
          contentType: "application/json",
          body: JSON.stringify({ task_id: "task-html-error", state: "queueing" }),
        });
        return;
      }
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ ready: true, templates: [{ id: "sweet-vitality", available: true }] }),
      });
    });
    await page.route("**/api/liveportrait/task-html-error", async (route) => {
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ state: "success", result_url: "/digital-human/opentalking/companion/action.mp4" }),
      });
    });
    await page.route("**/api/avatar-assets/candidates/provider", async (route) => {
      await route.fulfill({
        status: 502,
        contentType: "text/html",
        body: "<!DOCTYPE html><html><body>Bad Gateway</body></html>",
      });
    });

    await page.goto("/avatars/create?task=action&avatar_id=companion");
    const actionStudio = page.getByRole("region", { name: "动作创作" });
    await actionStudio.getByRole("button", { name: "生成动作" }).click();
    await expect(actionStudio.getByRole("button", { name: "创建动作资产" })).toBeEnabled();
    await actionStudio.getByRole("button", { name: "创建动作资产" }).click();

    await expect(actionStudio.getByText("动作候选保存失败（HTTP 502）")).toBeVisible();
    await expect(actionStudio.getByText(/Unexpected token/)).toHaveCount(0);
  });

  test("keeps the recycle bin reachable from asset management", async ({ page }) => {
    await page.goto("/avatars");
    await page.getByRole("link", { name: "回收站" }).click();

    await expect(page).toHaveURL(/\/avatars\/trash$/);
    await expect(page.getByRole("heading", { name: "回收站" })).toBeVisible();
    await expect(page.getByText("删除的 Avatar 和动作保留 30 天")).toBeVisible();
  });

  test("handles an unknown Avatar detail route", async ({ page }) => {
    await page.goto("/avatars/avatar-does-not-exist");

    await expect(page.getByRole("heading", { name: "找不到这个 Avatar" })).toBeVisible();
    await expect(page.getByRole("link", { name: "返回资产管理" }).last()).toBeVisible();
  });
});

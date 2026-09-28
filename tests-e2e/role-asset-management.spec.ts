import { expect, test, type Page } from "@playwright/test";
import { resolve } from "node:path";
import type { OwnedAvatarRecord } from "../src/lib/avatar-records";

function fixture(personal = false): OwnedAvatarRecord {
  return { avatar_id: personal ? "avatar-personal-test" : "avatar-test", display_name: "测试形象", source_image_url: "/digital-human/avatar1.png", created_at: "2026-09-01", updated_at: "2026-09-01", deleted_at: null, realtime_binding: null, actions: [{ avatar_action_id: "action-test", display_name: "测试底片", video_url: "/digital-human/builtin-motion/shuchang-realtime-idle.mp4", pending_model_count: 0, created_at: "2026-09-01", deleted_at: null, talking_variants: [{ id: "variant-test", display_name: "测试口型", method: "lipforcing", source_video_url: "/digital-human/builtin-motion/shuchang-realtime-idle.mp4", video_url: "/digital-human/builtin-motion/shuchang-realtime-idle.mp4", processing: "original", validation: "pending" }] }] };
}
async function setup(page: Page, personal = false) {
  const avatar = fixture(personal);
  const mutations: string[] = [];
  await page.route("**/api/**", async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    let payload: unknown = {};
    if (path === "/api/avatars") payload = { avatars: personal ? [] : [avatar] };
    else if (path === "/api/user/avatars") payload = { avatars: personal ? [avatar] : [] };
    else if (path === "/api/roles/role-test") payload = { role: { role_id: "role-test", display_name: "测试角色", avatar_id: avatar.avatar_id, avatar_image_url: avatar.source_image_url, persona_id: null, persona_name: null, voice_provider: "doubao", voice_id: "test-voice", enabled_modes: ["offline"], default_mode: "offline", default_selections: { offline: { action_id: "action-test", talking_variant_id: "variant-test" } }, memory_enabled: true, tool_ids: [], created_at: "", updated_at: "", deleted_at: null } };
    else if (request.method() === "PATCH" && path.includes(`/avatars/${avatar.avatar_id}`)) {
      const body = request.postDataJSON(); mutations.push(`${path}:${body.operation}`);
      const action = avatar.actions[0];
      const target = path.endsWith("/variant-test") ? action.talking_variants![0] : path.endsWith("/action-test") ? action : avatar;
      if (body.operation === "rename") target.display_name = body.displayName;
      else if (body.operation === "trash") target.deleted_at = "2026-09-28";
      else if (body.operation === "restore") target.deleted_at = null;
      else if (body.operation === "replaceSourceImage") { avatar.source_image_url = body.sourceImageDataUrl; avatar.actions.forEach(item => { item.deleted_at = "2026-09-28"; }); }
      payload = path === `/api/avatars/${avatar.avatar_id}` || path === `/api/user/avatars/${avatar.avatar_id}` ? { avatar } : { action };
    } else if (path === "/api/personas") payload = { personas: [] };
    else if (path === "/api/tools") payload = { tools: [] };
    else if (path === "/api/knowledge") payload = { documents: [] };
    else if (path.includes("/api/knowledge/bindings/")) payload = { documentIds: [] };
    else if (path === "/api/anam/avatars") payload = { avatars: [], configured: false };
    else if (path === "/api/user/session") payload = { user: null };
    else if (path === "/api/github-stars") payload = { stars: 0 };
    else if (path === "/api/avatar-capabilities") return route.fulfill({ status: 503, json: { error: "test" } });
    await route.fulfill({ json: payload });
  });
  return { avatar, mutations };
}
async function openModule(page: Page, title: string) {
  const button = page.getByRole("button", { name: new RegExp(`^${title}`) }).filter({ has: page.locator("em") });
  if (await button.getAttribute("aria-expanded") !== "true") await button.click();
}
async function menu(page: Page, kind: string, name: string, operation: string) {
  await page.locator(`summary[aria-label="管理${kind}：${name}"]`).click();
  await page.getByRole("button", { name: operation, exact: true }).click();
}

test("role detail renames and restores shapes without leaving the editor", async ({ page }) => {
  await setup(page);
  await page.goto("/roles/role-test");
  await page.getByRole("button", { name: "打开角色配置" }).click();
  await openModule(page, "数字人形象");
  await menu(page, "形象", "测试形象", "更名");
  await page.getByLabel("新名称").fill("新的形象");
  await page.getByRole("button", { name: "确认", exact: true }).click();
  await expect(page.locator('summary[aria-label="管理形象：新的形象"]')).toBeVisible();
  await menu(page, "形象", "新的形象", "删除");
  await expect(page.getByRole("dialog")).toContainText("其他角色");
  await page.getByRole("button", { name: "确认", exact: true }).click();
  await expect(page.locator('summary[aria-label="管理形象：新的形象"]')).toHaveCount(0);
  await page.getByText("已删除（1）", { exact: true }).click();
  await page.getByRole("button", { name: "恢复", exact: true }).click();
  await page.getByRole("button", { name: "确认", exact: true }).click();
  await expect(page.locator('summary[aria-label="管理形象：新的形象"]')).toBeVisible();
  await expect(page).toHaveURL(/\/roles\/role-test$/);
});

test("role editor deletes only the paired mouth material and restores it", async ({ page }) => {
  await setup(page);
  await page.goto("/roles/role-test");
  await page.getByRole("button", { name: "打开角色配置" }).click();
  await openModule(page, "口型对齐");
  await menu(page, "口型对齐", "测试口型", "删除");
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await expect(page.getByRole("button", { name: "选择口型对齐 测试口型", exact: true })).toBeVisible();
  await menu(page, "口型对齐", "测试口型", "更名");
  await page.getByLabel("新名称").fill("新口型");
  await page.getByRole("button", { name: "确认", exact: true }).click();
  await menu(page, "口型对齐", "新口型", "删除");
  await page.getByRole("button", { name: "确认", exact: true }).click();
  await expect(page.getByRole("button", { name: "选择口型对齐 新口型", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^口型对齐/ }).filter({ has: page.locator("em") })).toContainText("待配置");
  await page.getByText("已删除（1）", { exact: true }).click();
  await page.getByRole("button", { name: "恢复", exact: true }).click();
  await page.getByRole("button", { name: "确认", exact: true }).click();
  await expect(page.getByRole("button", { name: "选择口型对齐 新口型", exact: true })).toBeVisible();
});

test("role editor deletes a base and clears preview selections", async ({ page }) => {
  await setup(page);
  await page.goto("/roles/role-test");
  await page.getByRole("button", { name: "打开角色配置" }).click();
  await openModule(page, "动作底片");
  await menu(page, "动作底片", "测试底片", "删除");
  await page.getByRole("button", { name: "确认", exact: true }).click();
  await expect(page.getByRole("button", { name: "选择动作 测试底片", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^动作底片/ }).filter({ has: page.locator("em") })).toContainText("待配置");
  await page.getByText("已删除（1）", { exact: true }).click();
  await page.getByRole("button", { name: "恢复", exact: true }).click();
  await page.getByRole("button", { name: "确认", exact: true }).click();
  await expect(page.getByRole("button", { name: "选择动作 测试底片", exact: true })).toBeVisible();
});

test("personal menus expose rename without unsupported deletion", async ({ page }) => {
  const { mutations } = await setup(page, true);
  await page.goto("/roles/role-test");
  await page.getByRole("button", { name: "打开角色配置" }).click();
  await openModule(page, "动作底片");
  await page.locator('summary[aria-label="管理动作底片：测试底片"]').click();
  await expect(page.getByRole("button", { name: "删除", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "更名", exact: true }).click();
  await page.getByLabel("新名称").fill("个人底片");
  await page.getByRole("button", { name: "确认", exact: true }).click();
  await expect(page.getByRole("button", { name: "选择动作 个人底片", exact: true })).toBeVisible();
  expect(mutations).toContain("/api/user/avatars/avatar-personal-test/actions/action-test:rename");
});


test("changing the shape image retires bases and Escape preserves the editor", async ({ page }) => {
  const { mutations } = await setup(page);
  await page.goto("/roles/role-test");
  await page.getByRole("button", { name: "打开角色配置" }).click();
  await openModule(page, "数字人形象");
  await menu(page, "形象", "测试形象", "更名");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.locator('summary[aria-label="管理形象：测试形象"]')).toBeVisible();
  await menu(page, "形象", "测试形象", "更换图片");
  await expect(page.getByRole("dialog")).toContainText("原动作移入回收站");
  await page.getByLabel("新图片").setInputFiles(resolve("public/digital-human/avatar2.png"));
  await page.getByRole("button", { name: "确认", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await openModule(page, "动作底片");
  await expect(page.getByRole("button", { name: "选择动作 测试底片", exact: true })).toHaveCount(0);
  await expect(page.getByText("已删除（1）", { exact: true })).toBeVisible();
  expect(mutations).toContain("/api/avatars/avatar-test:replaceSourceImage");
});

test("failed rename keeps the original choice and allows retry", async ({ page }) => {
  await setup(page);
  let failed = false;
  await page.route("**/api/avatars/avatar-test/actions/action-test", async route => {
    if (!failed) { failed = true; await route.fulfill({ status: 503, json: { error: "暂时保存失败" } }); }
    else await route.fallback();
  });
  await page.goto("/roles/role-test");
  await page.getByRole("button", { name: "打开角色配置" }).click();
  await openModule(page, "动作底片");
  await menu(page, "动作底片", "测试底片", "更名");
  await page.getByLabel("新名称").fill("新底片");
  await page.getByRole("button", { name: "确认", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("暂时保存失败");
  await expect(page.getByRole("button", { name: "选择动作 测试底片", exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "确认", exact: true }).click();
  await expect(page.getByRole("button", { name: "选择动作 新底片", exact: true })).toHaveAttribute("aria-pressed", "true");
});

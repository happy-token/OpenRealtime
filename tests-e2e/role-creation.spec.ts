import { expect, test, type Page } from "@playwright/test";

function role(id: string, name = "已有角色") {
  return { role_id: id, display_name: name, avatar_id: null, avatar_image_url: null, persona_id: null, persona_name: null, voice_provider: "doubao", voice_id: "test-voice", enabled_modes: ["conversation"], default_mode: "conversation", default_selections: {}, memory_enabled: true, tool_ids: [], created_at: "", updated_at: "", deleted_at: null };
}
async function setup(page: Page, options: { signedIn?: boolean; local?: boolean; providerStatus?: number; provider?: string } = {}) {
  const posted: string[] = [];
  const createdId = options.signedIn ? "role-personal-created" : "role-local-created";
  await page.route("**/api/**", async route => {
    const request = route.request(); const path = new URL(request.url()).pathname;
    if (path === "/api/provider-instances") return route.fulfill({ status: options.providerStatus ?? 200, json: options.provider ? { pipelineFallbacks: { tts: { provider: options.provider } } } : { instances: [], selections: {}, platformCredentials: [] } });
    if (path === "/api/user/roles" && !options.signedIn) return route.fulfill({ status: 401, json: { error: "请先登录" } });
    if (path === "/api/user/roles" || path === "/api/roles") {
      if (request.method() === "POST") {
        posted.push(path);
        if (path === "/api/roles" && !options.local) return route.fulfill({ status: 403, json: { error: "不允许创建角色" } });
        const input = request.postDataJSON();
        return route.fulfill({ status: 201, json: { role: { ...role(createdId, input.displayName), voice_provider: input.voiceProvider, voice_id: input.voiceId } } });
      }
      return route.fulfill({ json: { roles: path === "/api/roles" ? [role("role-existing")] : [] } });
    }
    if (path === `/api/user/roles/${createdId}` || path === `/api/roles/${createdId}`) return route.fulfill({ json: { role: role(createdId, "未命名角色") } });
    if (path === "/api/user/me") return route.fulfill({ json: options.signedIn ? { signedIn: true, user: { issuer: "test", subject: "test" } } : { signedIn: false } });
    if (path.includes("/avatars")) return route.fulfill({ json: { avatars: [] } });
    if (path === "/api/personas") return route.fulfill({ json: { personas: [] } });
    if (path === "/api/tools") return route.fulfill({ json: { tools: [] } });
    if (path === "/api/knowledge") return route.fulfill({ json: { documents: [] } });
    if (path.includes("/knowledge/bindings/")) return route.fulfill({ json: { documentIds: [] } });
    if (path === "/api/avatar-capabilities") return route.fulfill({ status: 503, json: {} });
    await route.fulfill({ json: {} });
  });
  return { posted, createdId };
}

for (const status of [401, 503]) {
  test(`local draft creation works when voice configuration returns ${status}`, async ({ page }) => {
    const { posted, createdId } = await setup(page, { local: true, providerStatus: status });
    await page.goto("/roles");
    await page.getByRole("button", { name: "新建角色", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/roles/${createdId}\\?settings=1$`));
    await expect(page.getByRole("button", { name: "打开角色配置" })).toBeVisible();
    await expect(page.getByRole("complementary", { name: "角色配置", exact: true })).toBeVisible();
    expect(posted).toEqual(["/api/roles"]);
  });
}

test("signed-in users can create drafts before configuring TTS", async ({ page }) => {
  const { posted, createdId } = await setup(page, { signedIn: true });
  await page.goto("/roles");
  await page.getByRole("button", { name: "新建角色", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/roles/${createdId}\\?settings=1$`));
  const panel = page.getByRole("complementary", { name: "角色配置", exact: true });
  await expect(panel).toBeVisible();
  await expect(panel.locator("header input")).toHaveCount(0);
  await expect(panel.getByRole("textbox", { name: /角色名称/ })).toHaveCount(1);
  await expect(panel.getByRole("button", { name: "编辑角色名称", exact: true })).toHaveCount(0);
  await panel.getByRole("button", { name: "编辑", exact: true }).click();
  await panel.getByRole("textbox", { name: /角色名称/ }).fill("新的角色名称");
  await expect(panel.locator("header")).toContainText("新的角色名称");
  expect(posted).toEqual(["/api/user/roles"]);
});

test("production asks for login and keeps the existing role list usable", async ({ page }) => {
  await setup(page, { providerStatus: 401 });
  await page.goto("/roles");
  await expect(page.getByRole("link", { name: "查看已有角色详情" })).toBeVisible();
  await page.getByRole("button", { name: "新建角色", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "角色创建失败" })).toContainText("请先登录后创建角色");
  await expect(page.getByRole("link", { name: "登录后创建" })).toHaveAttribute("href", "/api/user/login?next=%2Froles");
  await expect(page.getByRole("link", { name: "查看已有角色详情" })).toBeVisible();
  await expect(page.getByRole("button", { name: "新建角色", exact: true })).toBeEnabled();
});

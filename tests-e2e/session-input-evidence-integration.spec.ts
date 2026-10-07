import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";

const sessionId = "recording-browser-session";
const root = `/api/observability/sessions/${sessionId}/diagnostics`;
test("owned Session input evidence joins real HTTP, administrator pagination and no-Cookie Agent", async ({ page, context, playwright, baseURL }) => {
  test.skip(process.env.RUN_RECORDING_BROWSER_INTEGRATION !== "1", "requires the owned isolated Runtime/PG fixture");
  test.setTimeout(60_000);
  if (baseURL !== "http://127.0.0.1:3029" || !/^voiceagent_recording_browser_[a-f0-9]{32}$/.test(process.env.VOICEAGENT_POSTGRES_SCHEMA ?? "")) throw new Error("owned isolated fixture required");
  const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
  await context.addCookies([{ name: "openrealtime_user_session", value: "recording-test-only-cookie-token-0000000000000", url: baseURL, httpOnly: true, sameSite: "Lax" }]);
  await page.goto(`/settings/session-diagnostics/sessions/${sessionId}`);
  await page.getByRole("tab", { name: "输入证据" }).click();
  const panel = page.getByRole("tabpanel");
  await expect(panel.getByRole("button")).toHaveCount(0);
  await expect(panel.locator("details")).toHaveCount(100);
  await expect(panel).toContainText("记录使用临时存储");
  let failed = false;
  await page.route(`**${root}?input_cursor=100`, async route => {
    if (!failed) { failed = true; await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: "fixture paging outage" }) }); }
    else await route.continue();
  });
  await page.getByRole("button", { name: "加载更多日志" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "日志续页读取失败" })).toContainText("日志续页读取失败");
  await expect(panel.locator("details")).toHaveCount(100);
  await page.getByRole("button", { name: "加载更多日志" }).click();
  await expect(panel.locator("details")).toHaveCount(101);
  await expect(page.getByRole("button", { name: "加载更多日志" })).toHaveCount(0);
  await panel.locator("details").last().locator("summary").click();
  await expect(panel.locator("details").last()).toContainText("fixture revision 101");
  const [download, signed] = await Promise.all([
    page.waitForEvent("download", { timeout: 15_000 }),
    page.waitForResponse(response => response.url().endsWith(`${root}/access`) && response.request().method() === "POST", { timeout: 15_000 }),
    page.getByRole("button", { name: "生成 Agent 只读凭据" }).click(),
  ]);
  expect(signed.status()).toBe(201);
  const path = await download.path();
  if (!path) throw new Error("Agent grant file missing");
  const grant = JSON.parse(await readFile(path, "utf8"));
  expect(grant.pagination.input_evidence).toBe("input_evidence.next_cursor → input_cursor");
  const token: string = grant.access_token;
  const agent = await playwright.request.newContext({ baseURL });
  try {
    const headers = { Authorization: `Bearer ${token}` };
    const first = await agent.get(root, { headers }), body = await first.json();
    expect(first.status()).toBe(200); expect(body.collection_health).toBeNull();
    expect(body.input_evidence.records).toHaveLength(100); expect(body.input_evidence.next_cursor).toBe("100");
    expect(body.input_evidence.records.every((row: { voice_session_id: string }) => row.voice_session_id === sessionId)).toBe(true);
    const last = await agent.get(`${root}?input_cursor=100`, { headers }), tail = await last.json();
    expect(last.status()).toBe(200); expect(tail.input_evidence.records).toHaveLength(1);
    expect(tail.input_evidence.records[0].sequence).toBe("101"); expect(tail.input_evidence.next_cursor).toBeNull();
    expect((await agent.get(root.replace(sessionId, "foreign"), { headers })).status()).toBe(403);
  } finally { await agent.dispose(); }
  expect(errors).toEqual([]);
});

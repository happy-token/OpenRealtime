import { createHash } from "node:crypto";
import { test, expect } from "@playwright/test";
import { issueDiagnosticsAccess } from "../src/lib/diagnostics-access";

const sessionId = "recording-browser-session";
const root = `/api/observability/sessions/${sessionId}/recordings`;

test("isolated administrator reads verified WAV and preserves the original Session", async ({ page, context, playwright, baseURL }) => {
  test.skip(process.env.RUN_RECORDING_BROWSER_INTEGRATION !== "1", "requires the owned isolated Runtime/PG fixture");
  test.setTimeout(90_000);
  if (!baseURL) throw new Error("isolated baseURL required");
  if (new URL(baseURL).hostname !== "127.0.0.1" || new URL(baseURL).port !== "3029"
    || !/^voiceagent_recording_browser_[a-f0-9]{32}$/.test(process.env.VOICEAGENT_POSTGRES_SCHEMA ?? "")) {
    throw new Error("requires the isolated 3029 server and owned fixture schema");
  }
  await context.addCookies([{ name: "openrealtime_user_session", value: "recording-test-only-cookie-token-0000000000000", url: baseURL, httpOnly: true, sameSite: "Lax" }]);
  await page.goto(`/settings/session-diagnostics/sessions/${sessionId}`);
  const panel = page.getByRole("region", { name: "会话录音" });
  await expect(panel).toBeVisible();
  await panel.getByRole("button", { name: "查看录音" }).click();
  await expect(panel).toContainText("用户输入");
  await expect(panel.getByRole("button", { name: "长期保留", exact: true })).toBeEnabled();

  await panel.getByRole("button", { name: "播放片段" }).click();
  const audio = panel.locator("audio");
  await expect(audio).toHaveAttribute("preload", "none");
  const audioResponse = page.waitForResponse(response => response.url().includes(`${root}/`) && !response.url().endsWith("/preservation"));
  await audio.evaluate(async (element: HTMLAudioElement) => { await element.play(); });
  const wavResponse = await audioResponse;
  expect([200, 206]).toContain(wavResponse.status());
  expect(wavResponse.headers()["content-type"]).toBe("audio/wav");
  if (wavResponse.status() === 206) expect(wavResponse.headers()["content-range"]).toMatch(/^bytes 0-\d+\/3244$/);
  await expect.poll(() => audio.evaluate((element: HTMLAudioElement) => element.duration)).toBeCloseTo(0.1, 2);
  await expect.poll(() => audio.evaluate((element: HTMLAudioElement) => element.ended)).toBe(true);

  const markedResponse = page.waitForResponse(response => response.url().endsWith(`${root}/preservation`) && response.request().method() === "POST");
  await panel.getByRole("button", { name: "长期保留", exact: true }).click();
  const marked = await markedResponse;
  expect(marked.status(), JSON.stringify(await marked.json())).toBe(200);
  await expect(panel.getByRole("button", { name: "已长期保留" })).toBeDisabled();
  await expect(panel).toContainText("已验证保留 1 段");
  await expect(panel).toContainText("临时存储，重启后不保留");
  await expect(panel).toContainText("可读取 · 已保留");

  const grant = issueDiagnosticsAccess(sessionId, "isolated-agent", process.env.OPENREALTIME_DIAGNOSTICS_ACCESS_SECRET);
  const authorization = `Bearer ${grant.access_token}`;
  const anonymous = await playwright.request.newContext({ baseURL });
  try {
    const agentPage = await anonymous.get(root, { headers: { Authorization: authorization } });
    expect(agentPage.status()).toBe(200);
    const catalog = await agentPage.json();
    expect(catalog.preservation.status).toBe("preserved");
    expect(catalog.preservation).not.toHaveProperty("actor_id");
    const row = catalog.items[0];
    const wav = await anonymous.get(row.audio_url, { headers: { Authorization: authorization } });
    expect(wav.status()).toBe(200);
    const bytes = await wav.body();
    expect(bytes.subarray(0, 4).toString()).toBe("RIFF");
    expect(bytes.length).toBe(row.size_bytes);
    expect(createHash("sha256").update(bytes).digest("hex")).toBe(row.sha256);
    expect((await context.request.post(`${root}/preservation`, { headers: { Authorization: authorization, Origin: baseURL } })).status()).toBe(403);
    expect((await context.request.post(`${root}/preservation`, { headers: { Origin: "https://foreign.invalid" } })).status()).toBe(403);
    expect((await anonymous.post(`${root}/preservation`, { headers: { Authorization: authorization, Origin: baseURL } })).status()).toBe(403);
    expect((await anonymous.post(`${root}/preservation`, { headers: { Origin: baseURL } })).status()).toBe(403);
  } finally { await anonymous.dispose(); }

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await panel.getByRole("button", { name: "查看录音" }).click();
  await expect(panel.getByRole("button", { name: "已长期保留" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

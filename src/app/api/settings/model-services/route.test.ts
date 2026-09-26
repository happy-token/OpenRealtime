import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { NextRequest } from "next/server";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ADMIN_SESSION_COOKIE, createAdminSessionToken } from "@/lib/admin-auth";
import { GET, PATCH } from "./route";
import { POST as TEST_CONNECTION } from "./test/route";

const admin = { username: "admin", password: "long-password-123", sessionSecret: "s".repeat(32) };
let root: string;
beforeEach(async () => {
  root = await mkdtemp(path.join(os.tmpdir(), "model-services-route-"));
  vi.spyOn(process, "cwd").mockReturnValue(root);
  vi.stubEnv("VOICEAGENT_ADMIN_USERNAME", admin.username);
  vi.stubEnv("VOICEAGENT_ADMIN_PASSWORD", admin.password);
  vi.stubEnv("VOICEAGENT_ADMIN_SESSION_SECRET", admin.sessionSecret);
});
afterEach(async () => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  await rm(root, { recursive: true, force: true });
});

function request(method: "GET" | "PATCH" | "POST", body?: object, origin = "http://localhost:3010") {
  return new NextRequest("http://localhost:3010/api/settings/model-services", {
    method, headers: { cookie: `${ADMIN_SESSION_COOKIE}=${createAdminSessionToken(admin)}`, origin,
      ...(body ? { "content-type": "application/json" } : {}) },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
}

it("requires admin session and same-origin mutation", async () => {
  expect((await GET(new NextRequest("http://localhost:3010/api/settings/model-services"))).status).toBe(401);
  expect((await PATCH(request("PATCH", { kind: "wav2lip", url: "http://localhost:18192" }, "http://evil.example"))).status).toBe(403);
});

it("does not send an existing secret to a newly entered URL during a connection test", async () => {
  await PATCH(request("PATCH", { kind: "lipforcing", url: "http://127.0.0.1:18190", token: "private-token" }));
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: "ok", model: "lipforcing-14b" }), { status: 200 }));
  vi.stubGlobal("fetch", fetcher);
  const response = await TEST_CONNECTION(request("POST", { kind: "lipforcing", url: "http://localhost:19190" }));
  expect(response.status).toBe(200);
  expect(fetcher.mock.calls[0]?.[1]?.headers).toBeUndefined();
});

it("saves service URLs in the app and never returns token values", async () => {
  const saved = await PATCH(request("PATCH", { kind: "lipforcing", url: "http://127.0.0.1:18190", token: "private-token" }));
  expect(saved.status).toBe(200);
  expect(await saved.json()).toMatchObject({ url: "http://127.0.0.1:18190", tokenConfigured: true });
  const listed = await GET(request("GET"));
  const body = await listed.json();
  expect(body.services.lipforcing).toEqual({ url: "http://127.0.0.1:18190", tokenConfigured: true });
  expect(JSON.stringify(body)).not.toContain("private-token");
});

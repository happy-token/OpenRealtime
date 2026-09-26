import { mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { modelServiceConnection, normalizeModelServiceUrl, probeModelService, saveModelServiceConnection } from "./model-service-connections";

let root: string;
beforeEach(async () => {
  root = await mkdtemp(path.join(os.tmpdir(), "model-connections-test-"));
  vi.spyOn(process, "cwd").mockReturnValue(root);
});
afterEach(async () => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  await rm(root, { recursive: true, force: true });
});

it("saves editable URLs and private bearer tokens outside .env", async () => {
  await saveModelServiceConnection("lipforcing", { url: "http://127.0.0.1:18190/", token: "secret" });
  await saveModelServiceConnection("lipforcing", { url: "http://127.0.0.1:18190" });
  expect(await modelServiceConnection("lipforcing")).toEqual({ url: "http://127.0.0.1:18190", token: "secret" });
  const target = path.join(root, ".openrealtime", "model-service-connections.json");
  expect(JSON.parse(await readFile(target, "utf8"))).toMatchObject({ lipforcing: { token: "secret" } });
  await saveModelServiceConnection("lipforcing", { url: "http://localhost:18190" });
  expect(await modelServiceConnection("lipforcing")).toEqual({ url: "http://localhost:18190", token: "" });
  await saveModelServiceConnection("lipforcing", { url: "" });
  expect(await modelServiceConnection("lipforcing")).toEqual({ url: "", token: "" });
});

it("rejects unsafe URL formats", () => {
  for (const value of ["file:///etc/passwd", "http://user:password@localhost", "http://localhost/?secret=1", "javascript:alert(1)"]) {
    expect(() => normalizeModelServiceUrl(value)).toThrow();
  }
});

it("checks model identity and does not follow redirects", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ status: "ok", model: "musetalk" }), { status: 200 }))
    .mockResolvedValueOnce(new Response(null, { status: 302, headers: { location: "http://other/health" } }));
  vi.stubGlobal("fetch", fetcher);
  const connection = { url: "http://127.0.0.1:18190", token: "secret" };
  expect((await probeModelService("lipforcing", connection)).ready).toBe(false);
  expect((await probeModelService("lipforcing", connection)).ready).toBe(false);
  expect(fetcher.mock.calls[0]?.[1]).toMatchObject({ redirect: "manual", headers: { Authorization: "Bearer secret" } });
});

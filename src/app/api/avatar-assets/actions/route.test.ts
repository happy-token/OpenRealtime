import { afterEach, describe, expect, it, vi } from "vitest";
import { GET } from "./route";

afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });
function enableLocalTestMode() {
  vi.stubEnv("NODE_ENV", "development");
  vi.stubEnv("AVATAR_LOCAL_TEST_MODE", "true");
  vi.stubEnv("AVATAR_EVALUATION_LOOPBACK_BOUND", "true");
}
function request(query = "") {
  return new Request(`http://127.0.0.1:3010/api/avatar-assets/actions${query}`, { headers: { origin: "http://127.0.0.1:3010", "sec-fetch-site": "same-origin" } });
}
describe("Avatar action catalog route", () => {
  it("forwards the canonical cross-Avatar action library", async () => {
    enableLocalTestMode();
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ actions: [], selection: null }));
    vi.stubGlobal("fetch", fetcher);
    expect((await GET(request())).status).toBe(200);
    const url = new URL(String(fetcher.mock.calls[0][0]));
    expect(url.pathname).toBe("/avatar-assets/actions");
  });
  it("filters with avatar_id", async () => {
    enableLocalTestMode();
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ actions: [], selection: null }));
    vi.stubGlobal("fetch", fetcher);
    await GET(request("?avatarId=avatar-1"));
    expect(new URL(String(fetcher.mock.calls[0][0])).searchParams.get("avatar_id")).toBe("avatar-1");
  });
});

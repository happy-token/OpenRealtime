import { afterEach, describe, expect, it, vi } from "vitest";
import { GET } from "./route";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("GitHub Star count", () => {
  it("uses a server-side token for a private repository without exposing it in the response", async () => {
    vi.stubEnv("GITHUB_TOKEN", "test-secret");
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ stargazers_count: 12 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET();

    expect(fetchMock.mock.calls[0]?.[1]?.headers.Authorization).toBe("Bearer test-secret");
    expect(await response.json()).toEqual({ stars: 12 });
  });

  it("reports unavailable when GitHub cannot return a count", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 404 })));

    const response = await GET();

    expect(await response.json()).toEqual({ stars: null });
  });
});

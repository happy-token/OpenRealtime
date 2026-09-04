import { afterEach, describe, expect, it, vi } from "vitest";
import { GET } from "./route";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

function enableLocalTestMode() {
  vi.stubEnv("NODE_ENV", "development");
  vi.stubEnv("AVATAR_LOCAL_TEST_MODE", "true");
  vi.stubEnv("AVATAR_EVALUATION_LOOPBACK_BOUND", "true");
}

describe("Avatar artifact playback route", () => {
  it("preserves byte-range requests and playback response headers", async () => {
    enableLocalTestMode();
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response("ndid", {
      status: 206,
      headers: {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, max-age=3600, immutable",
        "Content-Length": "4",
        "Content-Range": "bytes 2-5/15",
        "Content-Type": "video/mp4",
      },
    }));
    vi.stubGlobal("fetch", fetcher);

    const response = await GET(new Request(
      "http://127.0.0.1:3010/api/avatar-assets/artifacts/artifact-1",
      {
        headers: {
          origin: "http://127.0.0.1:3010",
          range: "bytes=2-5",
          "sec-fetch-site": "same-origin",
        },
      },
    ), { params: Promise.resolve({ artifactId: "artifact-1" }) });

    expect(fetcher).toHaveBeenCalledOnce();
    expect(fetcher.mock.calls[0][1]).toMatchObject({
      headers: { Range: "bytes=2-5" },
    });
    expect(response.status).toBe(206);
    expect(response.headers.get("accept-ranges")).toBe("bytes");
    expect(response.headers.get("cache-control")).toBe("private, max-age=3600, immutable");
    expect(response.headers.get("content-length")).toBe("4");
    expect(response.headers.get("content-range")).toBe("bytes 2-5/15");
    expect(await response.text()).toBe("ndid");
  });
});

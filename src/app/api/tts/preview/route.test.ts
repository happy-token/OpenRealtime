import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { GET } from "./route";

afterEach(() => vi.unstubAllGlobals());

describe("TTS preview public access", () => {
  it("rejects an ordinary visitor before calling the paid control plane", async () => {
    const upstream = vi.fn();
    vi.stubGlobal("fetch", upstream);
    const response = await GET(new NextRequest("https://example.com/api/tts/preview?provider=doubao"));

    expect(response.status).toBe(403);
    expect(upstream).not.toHaveBeenCalled();
  });
});

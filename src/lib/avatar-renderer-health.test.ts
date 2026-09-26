import { describe, expect, it, vi } from "vitest";
import { avatarRendererIsReady } from "./avatar-renderer-health";

describe("avatarRendererIsReady", () => {
  const env = { OPENREALTIME_AVATAR_RENDERER_MODE: "managed" };

  it("does not advertise a configured renderer until its health endpoint responds", async () => {
    const fetcher = vi.fn(async () => { throw new Error("connection refused"); }) as unknown as typeof fetch;
    expect(await avatarRendererIsReady(env, fetcher)).toBe(false);
    expect(fetcher).toHaveBeenCalledWith("http://127.0.0.1:8010/health", expect.objectContaining({ redirect: "manual" }));
  });

  it("requires the OpenRealtime renderer identity", async () => {
    expect(await avatarRendererIsReady(env, vi.fn(async () => Response.json({ renderer: "other" })) as typeof fetch)).toBe(false);
    expect(await avatarRendererIsReady(env, vi.fn(async () => Response.json({ renderer: "openrealtime" })) as typeof fetch)).toBe(true);
  });

  it("does not probe when the renderer is disabled", async () => {
    const fetcher = vi.fn() as unknown as typeof fetch;
    expect(await avatarRendererIsReady({ OPENREALTIME_AVATAR_RENDERER_MODE: "disabled" }, fetcher)).toBe(false);
    expect(fetcher).not.toHaveBeenCalled();
  });
});

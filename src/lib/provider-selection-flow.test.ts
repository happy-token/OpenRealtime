import { describe, expect, it, vi } from "vitest";
import { selectProviderInstanceForUse } from "./provider-selection-flow";

describe("provider instance selection flow", () => {
  it("tests an unverified personal instance before selecting it", async () => {
    const fetcher = vi.fn(async (url: string) => url.endsWith("/test")
      ? Response.json({ ok: true, message: "实时契约通过" })
      : Response.json({ instance: { id: "instance-1" } }));
    await expect(selectProviderInstanceForUse("instance-1", "untested", fetcher as typeof fetch))
      .resolves.toEqual({ tested: true });
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
      "/api/provider-instances/instance-1/test", "/api/provider-instances/instance-1/select",
    ]);
  });

  it("does not select a failed realtime contract", async () => {
    const fetcher = vi.fn(async () => Response.json({ ok: false, message: "缺少 ASR partial text" }));
    await expect(selectProviderInstanceForUse("instance-1", "failed", fetcher as typeof fetch))
      .rejects.toThrow("缺少 ASR partial text");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("selects a verified instance without repeating a billable test", async () => {
    const fetcher = vi.fn(async (_url: string) => Response.json({ instance: { id: "instance-1" } }));
    await expect(selectProviderInstanceForUse("instance-1", "passed", fetcher as typeof fetch))
      .resolves.toEqual({ tested: false });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0]?.[0]).toBe("/api/provider-instances/instance-1/select");
  });
});

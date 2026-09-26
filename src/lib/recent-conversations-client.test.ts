import { afterEach, describe, expect, it, vi } from "vitest";
import { clearRecentConversationCache, listRecentConversationsCached } from "./recent-conversations-client";

afterEach(() => {
  clearRecentConversationCache();
  vi.restoreAllMocks();
});

describe("recent conversation client cache", () => {
  it("reuses a fresh response and refreshes it on demand", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce(Response.json({ conversations: [{ id: "one", title: "One" }] }))
      .mockResolvedValueOnce(Response.json({ conversations: [{ id: "two", title: "Two" }] }));

    await expect(listRecentConversationsCached({ fetcher, now: 1_000 })).resolves.toEqual([{ id: "one", title: "One" }]);
    await expect(listRecentConversationsCached({ fetcher, now: 1_500 })).resolves.toEqual([{ id: "one", title: "One" }]);
    await expect(listRecentConversationsCached({ fetcher, now: 1_500, force: true })).resolves.toEqual([{ id: "two", title: "Two" }]);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("deduplicates concurrent requests", async () => {
    let resolve!: (response: Response) => void;
    const fetcher = vi.fn(() => new Promise<Response>((done) => { resolve = done; }));
    const first = listRecentConversationsCached({ fetcher, now: 1_000 });
    const second = listRecentConversationsCached({ fetcher, now: 1_000 });
    resolve(Response.json({ conversations: [{ id: "one", title: "One" }] }));

    await expect(Promise.all([first, second])).resolves.toEqual([
      [{ id: "one", title: "One" }],
      [{ id: "one", title: "One" }],
    ]);
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it("does not let an older request overwrite a forced refresh", async () => {
    let resolveOld!: (response: Response) => void;
    let resolveFresh!: (response: Response) => void;
    const fetcher = vi.fn()
      .mockImplementationOnce(() => new Promise<Response>((done) => { resolveOld = done; }))
      .mockImplementationOnce(() => new Promise<Response>((done) => { resolveFresh = done; }));

    const oldRequest = listRecentConversationsCached({ fetcher, now: 1_000 });
    const freshRequest = listRecentConversationsCached({ fetcher, now: 2_000, force: true });
    const freshFollower = listRecentConversationsCached({ fetcher, now: 2_000 });
    resolveFresh(Response.json({ conversations: [{ id: "fresh", title: "Fresh" }] }));
    await expect(Promise.all([freshRequest, freshFollower])).resolves.toEqual([
      [{ id: "fresh", title: "Fresh" }],
      [{ id: "fresh", title: "Fresh" }],
    ]);

    resolveOld(Response.json({ conversations: [{ id: "old", title: "Old" }] }));
    await expect(oldRequest).resolves.toEqual([{ id: "old", title: "Old" }]);
    await expect(listRecentConversationsCached({ fetcher, now: 2_500 })).resolves.toEqual([
      { id: "fresh", title: "Fresh" },
    ]);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});

import { LocalizedText } from "@/components/language/language-provider";
import { setImmediate } from "node:timers/promises";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ReactElement, ReactNode } from "react";
import { SessionRecordings } from "./session-recordings";

vi.mock("@/components/language/language-provider", () => ({
  useLanguage: () => ({ t: (text: string, params?: Record<string, string | number>) => text.replace(/\{([^}]+)\}/g, (match, key: string) => params?.[key] === undefined ? match : String(params[key])) }),
  LocalizedText: ({ text }: { text: ReactNode }) => text,
}));

// Controlled hook driver tests real handlers/state; not a DOM/audio renderer.
const driver = vi.hoisted(() => ({ slots: [] as unknown[], index: 0, cleanup: undefined as (() => void) | undefined }));
vi.mock("react", async importOriginal => ({
  ...await importOriginal<typeof import("react")>(),
  useState(initial: unknown) {
    const index = driver.index++;
    if (!(index in driver.slots)) driver.slots[index] = initial;
    return [driver.slots[index], (next: unknown) => {
      driver.slots[index] = typeof next === "function" ? next(driver.slots[index]) : next;
    }];
  },
  useRef(initial: unknown) {
    const index = driver.index++;
    if (!(index in driver.slots)) driver.slots[index] = { current: initial };
    return driver.slots[index];
  },
  useEffect(effect: () => (() => void)) { if (!driver.cleanup) driver.cleanup = effect(); },
}));
const fetchMock = vi.fn();
beforeEach(() => { driver.slots = []; driver.index = 0; driver.cleanup = undefined; vi.resetAllMocks(); vi.stubGlobal("fetch", fetchMock); });
afterEach(() => { vi.useRealTimers(); driver.cleanup?.(); });
function tree() { driver.index = 0; return SessionRecordings({ sessionId: "session-1" }); }
function nodes(value: ReactNode): ReactElement<Record<string, unknown>>[] {
  if (Array.isArray(value)) return value.flatMap(nodes);
  if (!value || typeof value !== "object" || !("props" in value)) return [];
  const element = value as ReactElement<Record<string, unknown>>;
  return [element, ...nodes(element.props.children as ReactNode)];
}
function text(value: ReactNode): string {
  if (Array.isArray(value)) return value.map(text).join("");
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (value && typeof value === "object" && "props" in value) {
    const element = value as ReactElement<{ children: ReactNode; text?: ReactNode }>;
    return text(element.type === LocalizedText ? element.props.text : element.props.children);
  }
  return "";
}
function click(label: string) {
  const button = nodes(tree()).find(node => node.type === "button" && text(node.props.children as ReactNode) === label);
  expect(button).toBeDefined(); (button!.props.onClick as () => void)();
}
function deferred() {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>(done => { resolve = done; });
  return { promise, resolve };
}
const row = (id: string) => ({ item_id: id, artifact_id: id, direction: "input", generation: 1, duration_ms: 10, sample_count: 160, sample_rate_hz: 16000, status: "available", pinned: false, storage_durable: false, discontinuity: false, audio_url: `/api/observability/sessions/session-1/recordings/${id}/audio` });
const page = (id: string, next: string | null) => Response.json({ voice_session_id: "session-1", items: [row(id)], next_cursor: next, storage_status: "configured" });
const unmarked = { status: "unmarked", marked_at: null, preserved_segments: null, pending_segments: null, unavailable_segments: null, storage_durable: false };
const marked = { status: "preserved", marked_at: "2026-10-07T00:00:00Z", preserved_segments: 1, pending_segments: 2, unavailable_segments: 3, storage_durable: false };
const policyPage = (preservation: unknown = unmarked, pinned = false) => Response.json({ voice_session_id: "session-1", items: [{ ...row("first"), pinned }], next_cursor: null, storage_status: "configured", preservation });
const markResult = () => Response.json({ voice_session_id: "session-1", preserved: true, ...marked });
it("shows numeric reported overlap with limits and leaves missing playback unknown", async () => {
  const playback = { status: "reported", overlap_samples: 80, reported_end_sample: 80, sample_rate_hz: 16000 };
  fetchMock.mockResolvedValueOnce(Response.json({ voice_session_id: "session-1", items: [{ ...row("sent"), direction: "sent", playback }], next_cursor: null, storage_status: "configured", playback_source: { status: "available", truncated: true, collection_healthy: false } }));
  click("查看录音");
  await vi.waitFor(() => expect(text(tree())).toContain("回执覆盖 0.005 / 0.010 秒"));
  expect(text(tree())).toContain("没有匹配回执不代表没有播放");
  const description = nodes(tree()).find(node => typeof node.props.title === "string" && node.props.title.includes("采样点"));
  expect(description?.props.title).toContain("80 / 160 个采样点");
  expect(description?.props.title).toContain("不证明扬声器实际播出或用户听到");
  fetchMock.mockResolvedValueOnce(Response.json({ voice_session_id: "session-1", items: [{ ...row("old"), direction: "sent" }], next_cursor: null, storage_status: "configured" }));
  click("刷新录音");
  await vi.waitFor(() => expect(text(tree())).toContain("播放位置未知"));
  expect(text(tree())).not.toContain("回执覆盖");
});

it("guards duplicate clicks, retains failed continuation and retries its original cursor", async () => {
  const first = deferred(); fetchMock.mockReturnValueOnce(first.promise);
  click("查看录音"); click("正在读取…");
  expect(fetchMock).toHaveBeenCalledTimes(1);
  first.resolve(page("first", "200"));
  await vi.waitFor(() => expect(text(tree())).toContain("加载更多录音"));
  fetchMock.mockResolvedValueOnce(Response.json({}, { status: 503 }));
  click("加载更多录音");
  await vi.waitFor(() => expect(text(tree())).toContain("录音目录读取失败"));
  expect(nodes(tree()).filter(node => node.type === "button" && text(node.props.children as ReactNode) === "播放片段")).toHaveLength(1);
  fetchMock.mockResolvedValueOnce(page("second", null)); click("加载更多录音");
  await vi.waitFor(() => expect(nodes(tree()).filter(node => node.type === "button" && text(node.props.children as ReactNode) === "播放片段")).toHaveLength(2));
  expect(fetchMock.mock.calls.slice(1).map(call => String(call[0]))).toEqual([
    "/api/observability/sessions/session-1/recordings?limit=200&after_sequence=200",
    "/api/observability/sessions/session-1/recordings?limit=200&after_sequence=200",
  ]);
});
it("refresh removes the selected player and restarts independent catalog pagination", async () => {
  fetchMock.mockResolvedValueOnce(page("first", "200")); click("查看录音");
  await vi.waitFor(() => expect(text(tree())).toContain("播放片段")); click("播放片段");
  const audio = nodes(tree()).find(node => node.type === "audio")!;
  expect(audio.props.src).toContain("/first/audio"); expect(audio.props.preload).toBe("none");
  const refreshing = deferred(); fetchMock.mockReturnValueOnce(refreshing.promise);
  click("刷新录音"); expect(nodes(tree()).some(node => node.type === "audio")).toBe(false);
  expect(String(fetchMock.mock.calls[1][0])).not.toContain("after_sequence");
  refreshing.resolve(page("refreshed", null));
  await vi.waitFor(() => expect(text(tree())).toContain("刷新录音"));
  expect(nodes(tree()).filter(node => node.type === "button" && text(node.props.children as ReactNode) === "播放片段")).toHaveLength(1);
});
it("unmount aborts the request and ignores a noncooperative late response", async () => {
  const pending = deferred(); fetchMock.mockReturnValueOnce(pending.promise); click("查看录音");
  const signal = fetchMock.mock.calls[0][1].signal as AbortSignal;
  driver.cleanup!(); expect(signal.aborted).toBe(true);
  const before = [...driver.slots]; pending.resolve(page("late", null));
  // Await response parsing and both handler continuations, not a fake render.
  await pending.promise; await setImmediate();
  expect(driver.slots).toEqual(before);
  expect(nodes(tree()).some(node => node.type === "audio")).toBe(false);
});
it("preserves a Session once and refreshes rows before showing their pinned state", async () => {
  fetchMock.mockResolvedValueOnce(policyPage()); click("查看录音");
  await vi.waitFor(() => expect(text(tree())).toContain("播放片段")); click("播放片段");
  const mutation = deferred(), refresh = deferred();
  fetchMock.mockReturnValueOnce(mutation.promise).mockReturnValueOnce(refresh.promise);
  click("长期保留"); click("正在保留…"); expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(fetchMock.mock.calls[1][1].method).toBe("POST"); expect(fetchMock.mock.calls[1][1].body).toBeUndefined();
  mutation.resolve(markResult());
  await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
  expect(nodes(tree()).some(node => node.type === "audio")).toBe(false);
  expect(text(tree())).toContain("已验证保留 1 段"); expect(text(tree())).toContain("等待完成 2 段");
  expect(text(tree())).toContain("无法保留 3 段"); expect(text(tree())).toContain("重启后不保留");
  expect(text(tree())).not.toContain(" · 已保留");
  refresh.resolve(policyPage(marked, true));
  await vi.waitFor(() => expect(text(tree())).toContain("已长期保留"));
  expect(text(tree())).toContain(" · 已保留");
  expect(nodes(tree()).find(node => node.type === "button" && text(node.props.children as ReactNode) === "已长期保留")!.props.disabled).toBe(true);
});
it("keeps an unknown mutation result separate from success until an explicit catalog refresh", async () => {
  fetchMock.mockResolvedValueOnce(policyPage()); click("查看录音");
  await vi.waitFor(() => expect(text(tree())).toContain("播放片段"));
  fetchMock.mockResolvedValueOnce(Response.json({}, { status: 503 })); click("长期保留");
  await vi.waitFor(() => expect(text(tree())).toContain("保留结果尚未确认"));
  expect(text(tree())).not.toContain("已长期保留"); click("长期保留"); expect(fetchMock).toHaveBeenCalledTimes(2);
  fetchMock.mockResolvedValueOnce(policyPage(marked, true)); click("刷新录音");
  await vi.waitFor(() => expect(text(tree())).toContain("已长期保留"));
});
it("retains confirmed mark when its catalog refresh fails without pinning stale rows", async () => {
  fetchMock.mockResolvedValueOnce(policyPage()); click("查看录音");
  await vi.waitFor(() => expect(text(tree())).toContain("播放片段"));
  fetchMock.mockResolvedValueOnce(markResult()).mockResolvedValueOnce(Response.json({}, { status: 503 })); click("长期保留");
  await vi.waitFor(() => expect(text(tree())).toContain("目录刷新未完成"));
  expect(text(tree())).toContain("已长期保留"); expect(text(tree())).not.toContain(" · 已保留");
});
it("ignores a mark result after unmount and aborts its request", async () => {
  fetchMock.mockResolvedValueOnce(policyPage()); click("查看录音");
  await vi.waitFor(() => expect(text(tree())).toContain("播放片段"));
  const mutation = deferred(); fetchMock.mockReturnValueOnce(mutation.promise); click("长期保留");
  const signal = fetchMock.mock.calls[1][1].signal as AbortSignal;
  driver.cleanup!(); expect(signal.aborted).toBe(true);
  const before = [...driver.slots]; mutation.resolve(markResult());
  await mutation.promise; await setImmediate(); expect(driver.slots).toEqual(before); expect(fetchMock).toHaveBeenCalledTimes(2);
});
it("aborted late mark result is unconfirmed instead of silently enabling another mutation", async () => {
  fetchMock.mockResolvedValueOnce(policyPage()); click("查看录音");
  await vi.waitFor(() => expect(text(tree())).toContain("播放片段"));
  vi.useFakeTimers();
  const mutation = deferred(); fetchMock.mockReturnValueOnce(mutation.promise); click("长期保留");
  await vi.advanceTimersByTimeAsync(15_000);
  expect((fetchMock.mock.calls[1][1].signal as AbortSignal).aborted).toBe(true);
  mutation.resolve(markResult()); await mutation.promise; await setImmediate();
  expect(text(tree())).toContain("保留结果尚未确认"); expect(text(tree())).not.toContain("已长期保留");
  click("长期保留"); expect(fetchMock).toHaveBeenCalledTimes(2);
});

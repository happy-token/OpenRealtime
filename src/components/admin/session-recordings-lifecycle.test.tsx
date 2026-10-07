import { setImmediate } from "node:timers/promises";
import { beforeEach, expect, it, vi } from "vitest";
import type { ReactElement, ReactNode } from "react";
import { SessionRecordings } from "./session-recordings";

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
  if (value && typeof value === "object" && "props" in value) return text((value as ReactElement<{ children: ReactNode }>).props.children);
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

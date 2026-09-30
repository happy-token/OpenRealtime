import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ReactElement } from "react";
import { MotionOrchestrationStage } from "./motion-orchestration";
import { DEFAULT_AVATAR_DISPLAY_CONFIG } from "./types";
import { fetchOwnedAvatar } from "@/lib/avatar-catalog-client";
import type { OwnedAvatarRecord } from "@/lib/avatar-records";

// Exercise component handlers and effects in the repository's Node test environment.
const hooks = vi.hoisted(() => ({ states: [] as unknown[], index: 0, effects: [] as (() => void | (() => void))[] }));
vi.mock("react", async importOriginal => ({
  ...await importOriginal<typeof import("react")>(),
  useState: (initial: unknown) => {
    const index = hooks.index++;
    if (!(index in hooks.states)) hooks.states[index] = initial;
    return [hooks.states[index], (next: unknown) => {
      hooks.states[index] = typeof next === "function" ? next(hooks.states[index]) : next;
    }];
  },
  useRef: (value: unknown) => ({ current: value }),
  useEffect: (effect: () => void | (() => void)) => { hooks.effects.push(effect); },
  useSyncExternalStore: () => false,
}));
vi.mock("@/components/language/language-provider", () => ({ useLanguage: () => ({ t: (text: string) => text }) }));
vi.mock("@/lib/avatar-catalog-client", () => ({ fetchOwnedAvatar: vi.fn() }));

const config = { ...DEFAULT_AVATAR_DISPLAY_CONFIG, renderPath: "orchestrated" as const,
  segmentedAvatarId: "avatar-test", segmentedAvatarActionId: "base", motionTalkingVariantId: "talk" };

function render() {
  hooks.index = 0;
  hooks.effects = [];
  return MotionOrchestrationStage({ config });
}

function findElements(tree: unknown, predicate: (element: ReactElement<Record<string, unknown>>) => boolean): ReactElement<Record<string, unknown>>[] {
  if (Array.isArray(tree)) return tree.flatMap(item => findElements(item, predicate));
  if (!tree || typeof tree !== "object" || !("props" in tree)) return [];
  const element = tree as ReactElement<Record<string, unknown>>;
  return [...(predicate(element) ? [element] : []), ...findElements(element.props.children, predicate)];
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("window", globalThis);
  hooks.states = [false, { idle: "/idle.mp4", talking: "/talk.mp4" }, "/portrait.png", false, "talking failed", 1, 0, false];
  vi.mocked(fetchOwnedAvatar).mockReset();
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

it("keeps the available listening motion when continuing after talking-video failure", () => {
  const tree = render();
  const continueButton = findElements(tree, node => node.type === "button" && node.props.children === "使用当前画面继续")[0];
  (continueButton.props.onClick as () => void)();
  const degraded = render();
  const videos = findElements(degraded, node => node.type === "video");
  expect(videos).toHaveLength(1);
  expect(videos[0].props.src).toBe("/idle.mp4");
  expect(videos[0].props.style).toMatchObject({ opacity: 1 });
  expect(degraded.props["data-renderer-state"]).toBe("degraded");
});

it("shows a source-image fallback when the base video also failed", () => {
  hooks.states[0] = true;
  hooks.states[3] = true;
  const tree = render();
  expect(findElements(tree, node => node.type === "video")).toHaveLength(0);
  expect(findElements(tree, node => node.props.src === "/portrait.png")).toHaveLength(1);
});

it("replaces updated paired URLs during catalog refresh and waits for their load events", async () => {
  hooks.states[4] = "";
  hooks.states[5] = 3;
  vi.mocked(fetchOwnedAvatar).mockResolvedValue({ avatar_id: "avatar-test", actions: [{
    avatar_action_id: "base", video_url: "/new-idle.mp4", talking_variants: [{
      id: "talk", source_video_url: "/new-idle.mp4", video_url: "/new-talk.mp4",
    }],
  }] } as OwnedAvatarRecord);
  render();
  const cleanup = hooks.effects[1]();
  try {
    await vi.advanceTimersByTimeAsync(10_000);
    const tree = render();
    expect(findElements(tree, node => node.type === "video").map(node => node.props.src)).toEqual(["/new-idle.mp4", "/new-talk.mp4"]);
    expect(tree.props["data-renderer-state"]).toBe("connecting");
    expect(hooks.states[5]).toBe(0);
  } finally { if (typeof cleanup === "function") cleanup(); }
});

it("keeps the current pair after a transient catalog failure", async () => {
  vi.mocked(fetchOwnedAvatar).mockRejectedValue(new Error("temporary network failure"));
  render();
  const cleanup = hooks.effects[1]();
  try {
    await vi.advanceTimersByTimeAsync(10_000);
    expect(findElements(render(), node => node.type === "video").map(node => node.props.src)).toEqual(["/idle.mp4", "/talk.mp4"]);
  } finally { if (typeof cleanup === "function") cleanup(); }
});

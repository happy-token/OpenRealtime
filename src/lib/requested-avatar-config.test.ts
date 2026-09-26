import { afterEach, expect, it, vi } from "vitest";
import { DEFAULT_AVATAR_DISPLAY_CONFIG } from "@/components/digital-human/types";
import { loadRequestedAvatarConfig } from "./requested-avatar-config";

afterEach(() => vi.unstubAllGlobals());

it("replaces a saved local avatar with the requested hosted avatar without creating assets", async () => {
  const fetcher = vi.fn().mockResolvedValue(Response.json({ avatars: [
    { id: "samantha-id", displayName: "Samantha", imageUrl: "https://example.com/samantha.png" },
  ] }));
  vi.stubGlobal("fetch", fetcher);
  const signal = new AbortController().signal;
  const config = await loadRequestedAvatarConfig("anam-samantha-id", {
    ...DEFAULT_AVATAR_DISPLAY_CONFIG, renderPath: "segmented", segmentedAvatarId: "shuchang",
  }, signal);
  expect(config).toMatchObject({ renderPath: "hosted", provider: "anam", avatarProfileId: "samantha-id",
    hostedAvatarDisplayName: "Samantha", hostedAvatarImageUrl: "https://example.com/samantha.png" });
  expect(fetcher).toHaveBeenCalledExactlyOnceWith("/api/anam/avatars", { cache: "no-store", signal });
});

it("reports missing hosted avatars instead of retaining the previous selection silently", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ avatars: [] })));
  await expect(loadRequestedAvatarConfig("anam-missing", DEFAULT_AVATAR_DISPLAY_CONFIG,
    new AbortController().signal)).rejects.toThrow("所选 Anam 形象不存在");
});

it("preserves provider errors", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ error: "Anam 请求超时" }, { status: 503 })));
  await expect(loadRequestedAvatarConfig("anam-samantha-id", DEFAULT_AVATAR_DISPLAY_CONFIG,
    new AbortController().signal)).rejects.toThrow("Anam 请求超时");
});

it("keeps local avatar links and action selection working", async () => {
  const fetcher = vi.fn().mockResolvedValue(Response.json({ avatar: {
    avatar_id: "avatar-local", display_name: "Local", deleted_at: null, realtime_binding: null,
    actions: [{ avatar_action_id: "action-one", deleted_at: null }],
  } }));
  vi.stubGlobal("fetch", fetcher);
  const signal = new AbortController().signal;
  expect(await loadRequestedAvatarConfig("avatar-local", DEFAULT_AVATAR_DISPLAY_CONFIG, signal, "action-one"))
    .toMatchObject({ renderPath: "segmented", segmentedAvatarId: "avatar-local", segmentedAvatarActionId: "action-one" });
  expect(fetcher).toHaveBeenCalledExactlyOnceWith("/api/avatars/avatar-local", { cache: "no-store", signal });
});

it("uses a talking variant for an offline role session", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ avatar: {
    avatar_id: "avatar-local", display_name: "Local", deleted_at: null, realtime_binding: null,
    actions: [{
      avatar_action_id: "action-one", video_url: "/idle.mp4", deleted_at: null,
      talking_variants: [
        { id: "talk-one", method: "lipforcing", video_url: "/talk.mp4", source_video_url: "/idle.mp4", deleted_at: null },
        { id: "talk-two", method: "lipforcing", video_url: "/talk-2.mp4", source_video_url: "/idle.mp4", deleted_at: null },
      ],
    }],
  } })));
  const config = await loadRequestedAvatarConfig(
    "avatar-local",
    DEFAULT_AVATAR_DISPLAY_CONFIG,
    new AbortController().signal,
    "action-one",
    "offline",
    "talk-two",
  );
  expect(config).toMatchObject({
    renderPath: "orchestrated",
    segmentedAvatarActionId: "action-one",
    motionTalkingVariantId: "talk-two",
  });
});

it("rejects offline role sessions without talking material", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ avatar: {
    avatar_id: "avatar-local", display_name: "Local", deleted_at: null, realtime_binding: null,
    actions: [{ avatar_action_id: "action-one", video_url: "/idle.mp4", deleted_at: null }],
  } })));
  await expect(loadRequestedAvatarConfig(
    "avatar-local",
    DEFAULT_AVATAR_DISPLAY_CONFIG,
    new AbortController().signal,
    "action-one",
    "offline",
  )).rejects.toThrow("还没有可用的口型对齐");
});

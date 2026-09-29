import { afterEach, describe, expect, it, vi } from "vitest";
import type { OwnedAvatarRecord } from "./avatar-records";
import { collapseDuplicateOwnedAvatars, loadCurrentAvatarCatalog } from "./avatar-library-catalog-client";

function ownedAvatar(
  avatarId: string,
  displayName: string,
  updatedAt: string,
): OwnedAvatarRecord {
  return {
    avatar_id: avatarId,
    display_name: displayName,
    source_image_url: `/api/avatars/${avatarId}/image`,
    created_at: updatedAt,
    updated_at: updatedAt,
    deleted_at: null,
    realtime_binding: null,
    actions: [],
  };
}

describe("Avatar library catalog", () => {
  it("reuses the page's asset requests without fetching the catalogs again", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const avatar = ownedAvatar("avatar-shared-request", "共享请求", "2026-09-01T01:00:00.000Z");
    const catalog = await loadCurrentAvatarCatalog(undefined, {
      includeHostedAvatars: false,
      ownedAvatars: Promise.resolve([avatar]),
      personalAvatars: Promise.resolve([]),
    });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(catalog.some((item) => item.avatarId === avatar.avatar_id)).toBe(true);
  });

  it("keeps successful assets when one shared catalog request fails", async () => {
    const avatar = ownedAvatar("avatar-partial-request", "可用资产", "2026-09-01T01:00:00.000Z");
    const catalog = await loadCurrentAvatarCatalog(undefined, {
      includeHostedAvatars: false,
      ownedAvatars: Promise.resolve([avatar]),
      personalAvatars: Promise.reject(new Error("temporarily unavailable")),
    });
    expect(catalog.some((item) => item.avatarId === avatar.avatar_id)).toBe(true);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("collapses duplicate owned Avatar records and keeps the newest canonical record", () => {
    const records = collapseDuplicateOwnedAvatars([
      ownedAvatar("avatar-digital-human-1", "数字人1", "2026-09-01T01:00:00.000Z"),
      ownedAvatar("avatar-digital-human-2-old", "数字人2", "2026-09-01T02:42:54.657Z"),
      ownedAvatar("avatar-digital-human-2-new", " 数字人2 ", "2026-09-01T02:44:18.393Z"),
    ]);

    expect(records.map((record) => record.avatar_id)).toEqual([
      "avatar-digital-human-1",
      "avatar-digital-human-2-new",
    ]);
  });

  it("loads the selectable Avatar catalog without waiting for hosted or motion providers", async () => {
    const requestedUrls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      requestedUrls.push(String(input));
      return Response.json({ avatars: [] });
    }));

    await loadCurrentAvatarCatalog(undefined, {
      includeHostedAvatars: false,
    });

    expect(requestedUrls).not.toContain("/api/anam/avatars");
    expect(requestedUrls).not.toContain("/api/avatar-assets/actions");
    expect(requestedUrls).toContain("/api/avatars");
  });

  it("uses the managed Avatar aggregate instead of orphaned action-service records", async () => {
    const requestedUrls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      requestedUrls.push(url);
      if (url === "/api/avatars") {
        return Response.json({
          avatars: [ownedAvatar("shuchang", "傻妞", "2026-09-01T03:00:00.000Z")],
        });
      }
      if (url === "/api/avatar-assets/actions") {
        return Response.json({
          actions: [{
            avatar_action_id: "orphaned-upload",
            avatar_id: "shuchang",
            phase: "ready",
            renditions: [{ phase: "approved", artifact_id: "legacy-artifact" }],
          }],
          selection: null,
        });
      }
      return Response.json({ avatars: [] });
    }));

    const catalog = await loadCurrentAvatarCatalog();
    const shuchang = catalog.find((avatar) => avatar.avatarId === "shuchang");

    expect(shuchang?.actions.map((action) => action.avatarActionId)).toEqual([
      "builtin:shuchang-realtime-idle",
    ]);
    expect(requestedUrls).not.toContain("/api/avatar-assets/actions");
  });

  it("adds every LivePortrait companion action to Samantha without duplicating a saved action", async () => {
    const samantha = ownedAvatar(
      "avatar-8657be31-306e-428d-a013-7521e710ab6a",
      "萨曼莎",
      "2026-09-02T08:00:00.000Z",
    );
    samantha.actions = ["侧头微笑", "柔和回应", "忧郁共鸣"].map((displayName, index) => ({
      avatar_action_id: `saved-action-${index}`,
      display_name: displayName,
      video_url: `/api/avatar-assets/artifacts/saved-action-${index}`,
      pending_model_count: 0,
      created_at: "2026-09-02T08:00:00.000Z",
      deleted_at: null,
    }));
    samantha.actions.push(...["甜美元气", "纯欲柔光", "冷艳夜色", "知性温柔"].map((displayName, index) => ({
      avatar_action_id: `pending-action-${index}`,
      display_name: displayName,
      video_url: null,
      pending_model_count: 1,
      created_at: "2026-09-02T08:00:00.000Z",
      deleted_at: null,
    })));
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/avatars") return Response.json({ avatars: [samantha] });
      return Response.json({ avatars: [] });
    }));

    const defaultCatalog = await loadCurrentAvatarCatalog(undefined, { includeHostedAvatars: false });
    expect(defaultCatalog.find((avatar) => avatar.avatarId === samantha.avatar_id)?.actions)
      .toHaveLength(samantha.actions.length);

    const catalog = await loadCurrentAvatarCatalog(undefined, {
      includeHostedAvatars: false,
      includeOwnedBuiltinActions: true,
    });
    const actions = catalog.find((avatar) => avatar.avatarId === samantha.avatar_id)?.actions ?? [];
    const playableActions = actions.filter((action) => action.state === "available" && Boolean(action.videoUrl));

    expect(playableActions.map((action) => action.displayName)).toEqual([
      "侧头微笑",
      "柔和回应",
      "忧郁共鸣",
    ]);
    expect(playableActions.filter((action) => action.displayName === "忧郁共鸣")).toHaveLength(1);
    expect(playableActions.every((action) => Boolean(action.videoUrl))).toBe(true);
  });

  it("deduplicates built-in actions by action name when owned actions already exist", async () => {
    const samantha = ownedAvatar(
      "avatar-8657be31-306e-428d-a013-7521e710ab6a",
      "萨曼莎",
      "2026-09-02T08:00:00.000Z",
    );
    samantha.actions = [
      {
        avatar_action_id: "saved-sweet-vitality",
        display_name: "甜美元气",
        video_url: "/api/avatar-assets/artifacts/sweet-vitality",
        pending_model_count: 0,
        created_at: "2026-09-02T08:00:00.000Z",
        deleted_at: null,
      },
      {
        avatar_action_id: "owned-duplicate",
        display_name: " 甜美元气 ",
        video_url: "/api/avatar-assets/artifacts/duplicate-sweet-vitality",
        pending_model_count: 0,
        created_at: "2026-09-02T08:10:00.000Z",
        deleted_at: null,
      },
    ];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/avatars") return Response.json({ avatars: [samantha] });
      return Response.json({ avatars: [] });
    }));

    const catalog = await loadCurrentAvatarCatalog(undefined, {
      includeHostedAvatars: false,
      includeOwnedBuiltinActions: true,
    });
    const actions = catalog.find((avatar) => avatar.avatarId === samantha.avatar_id)?.actions ?? [];
    const names = actions.filter((action) => action.displayName.includes("甜美元气")).map((action) => action.avatarActionId);

    expect(actions).toHaveLength(5);
    expect(names).toHaveLength(1);
    expect(names[0]).toBe("saved-sweet-vitality");
  });
});

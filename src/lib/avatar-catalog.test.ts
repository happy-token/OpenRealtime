import { describe, expect, it } from "vitest";
import { buildAvatarCatalog, summarizeAvatarCapabilities } from "./avatar-catalog";

describe("AvatarCatalog", () => {
  it("groups one source image and multiple actions under one avatar_id", () => {
    const catalog = buildAvatarCatalog({
      avatars: [{
        avatar_id: "avatar-lin",
        display_name: "Lin",
        owner_id: "user-1",
        visibility: "private",
        source_image_url: "/images/lin.png",
      }],
      actions: [
        { avatar_action_id: "action-idle", avatar_id: "avatar-lin", display_name: "自然待机", state: "available" },
        { avatar_action_id: "action-smile", avatar_id: "avatar-lin", display_name: "微笑", state: "processing" },
      ],
      realtime_bindings: [{
        provider_avatar_id: "anam-42",
        avatar_id: "avatar-lin",
        provider: "anam",
        avatar_model: "cara-3",
        state: "accepted",
      }],
    });

    expect(catalog).toEqual([expect.objectContaining({
      avatarId: "avatar-lin",
      displayName: "Lin",
      source: { kind: "owned", imageUrl: "/images/lin.png" },
      actions: [
        expect.objectContaining({ avatarActionId: "action-idle", displayName: "自然待机" }),
        expect.objectContaining({ avatarActionId: "action-smile", displayName: "微笑" }),
      ],
      realtimeBinding: expect.objectContaining({ providerAvatarId: "anam-42", avatarModel: "cara-3" }),
    })]);
  });

  it("describes an image-only avatar as usable without calling it unconfigured", () => {
    const [avatar] = buildAvatarCatalog({
      avatars: [{
        avatar_id: "avatar-image-only",
        display_name: "Mira",
        owner_id: "user-1",
        visibility: "private",
        source_image_url: "/images/mira.png",
      }],
      actions: [],
      realtime_bindings: [],
    });

    expect(summarizeAvatarCapabilities(avatar)).toEqual({
      imageLabel: "可使用图片",
      actionLabel: "尚未创建动作",
      pendingActionCount: 0,
      realtimeLabel: null,
    });
  });

  it("keeps provider stock previews realtime-only", () => {
    const [avatar] = buildAvatarCatalog({
      avatars: [{
        avatar_id: "avatar-stock-liv",
        display_name: "Liv",
        owner_id: null,
        visibility: "shared",
        source_image_url: null,
        provider_preview_url: "https://provider.invalid/liv.png",
      }],
      actions: [],
      realtime_bindings: [{
        provider_avatar_id: "anam-stock-liv",
        avatar_id: "avatar-stock-liv",
        provider: "anam",
        avatar_model: "cara-3",
        state: "accepted",
      }],
    });

    expect(avatar.source).toEqual({ kind: "provider-preview", imageUrl: "https://provider.invalid/liv.png" });
    expect(avatar.canCreateActions).toBe(false);
    expect(summarizeAvatarCapabilities(avatar).realtimeLabel).toBe("Anam 内置 · 仅实时驱动");
  });
});

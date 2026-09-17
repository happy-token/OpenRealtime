import { mkdtemp, rm, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  appendOwnedAvatarAction,
  attachTalkingVariant,
  createOwnedAvatar,
  findOwnedAvatar,
  listOwnedAvatars,
  readOwnedAvatarImage,
  replaceOwnedAvatarSourceImage,
  updateOwnedAvatar,
  updateOwnedAvatarAction,
} from "./avatar-catalog-repository";

const roots: string[] = [];
const jpeg = `data:image/jpeg;base64,${Buffer.from([0xff, 0xd8, 0xff, 0xd9]).toString("base64")}`;
const pngBytes = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
const png = `data:image/png;base64,${pngBytes.toString("base64")}`;

afterEach(async () => {
  await Promise.all(roots.splice(0).map((root) => rm(root, { recursive: true, force: true })));
});

async function repositoryRoot() {
  const root = await mkdtemp(path.join(tmpdir(), "openrealtime-avatar-catalog-"));
  roots.push(root);
  return root;
}

describe("Avatar catalog repository", () => {
  it.each([{}, [{ avatar_id: "avatar-invalid" }]])("preserves an invalid catalog instead of overwriting it: %j", async (invalid) => {
    const root = await repositoryRoot();
    const catalog = path.join(root, "catalog.json");
    const original = JSON.stringify(invalid);
    await writeFile(catalog, original);
    await expect(listOwnedAvatars(root)).rejects.toThrow("目录结构异常");
    await expect(createOwnedAvatar({ displayName: "New", sourceImageDataUrl: jpeg }, root))
      .rejects.toThrow("目录结构异常");
    expect(await readFile(catalog, "utf8")).toBe(original);
  });

  it("does not drop valid neighbors when a stored record is invalid", async () => {
    const root = await repositoryRoot();
    await createOwnedAvatar({ displayName: "Lin", sourceImageDataUrl: jpeg, avatarId: "avatar-123" }, root);
    const catalog = path.join(root, "catalog.json");
    const records = JSON.parse(await readFile(catalog, "utf8"));
    const original = JSON.stringify([...records, { avatar_id: "avatar-broken" }]);
    await writeFile(catalog, original);
    await expect(updateOwnedAvatar("avatar-123", { displayName: "Changed" }, root))
      .rejects.toThrow("目录结构异常");
    expect(await readFile(catalog, "utf8")).toBe(original);
  });

  it.each(["minimax", "musetalk", "lipforcing"] as const)("keeps %s talking variants nested, idempotent and bound to the source", async (method) => {
    const root = await repositoryRoot();
    await createOwnedAvatar({ displayName: "Lin", sourceImageDataUrl: jpeg, avatarId: "avatar-123" }, root);
    await appendOwnedAvatarAction("avatar-123", { avatar_action_id: "base", display_name: "Base", video_url: "/base.mp4" }, root);
    const variant = { id: "talk-v2", display_name: "Talking", method, source_video_url: "/base.mp4", video_url: "/digital-human/talking-variants/talk-v2.mp4", processing: "original" as const, validation: "pending" as const };
    await attachTalkingVariant("avatar-123", "base", variant, root);
    await attachTalkingVariant("avatar-123", "base", variant, root);
    const avatar = await findOwnedAvatar("avatar-123", root);
    expect(avatar?.actions).toHaveLength(1);
    expect(avatar?.actions[0].talking_variants).toEqual([variant]);
    await expect(attachTalkingVariant("avatar-123", "base", { ...variant, source_video_url: "/other.mp4" }, root)).rejects.toThrow("不匹配");
  });

  it("persists one immutable source image under avatar_id", async () => {
    const root = await repositoryRoot();
    const avatar = await createOwnedAvatar({ displayName: "Lin", sourceImageDataUrl: jpeg, avatarId: "avatar-123" }, root);

    expect(avatar).toMatchObject({ avatar_id: "avatar-123", display_name: "Lin" });
    expect(avatar.source_image_url).toBe("/api/avatars/avatar-123/image");
    expect(await listOwnedAvatars(root)).toEqual([avatar]);
    expect((await readOwnedAvatarImage("avatar-123", root))?.mediaType).toBe("image/jpeg");
  });

  it("stores multiple actions and their preparation state in the Avatar aggregate", async () => {
    const root = await repositoryRoot();
    await createOwnedAvatar({ displayName: "Lin", sourceImageDataUrl: jpeg, avatarId: "avatar-123" }, root);
    await appendOwnedAvatarAction("avatar-123", {
      avatar_action_id: "action-1",
      display_name: "自然待机",
      video_url: "/api/avatar-assets/artifacts/a1",
      pending_model_count: 1,
    }, root);
    await updateOwnedAvatarAction("avatar-123", "action-1", { pendingModelCount: 0 }, root);

    expect((await findOwnedAvatar("avatar-123", root))?.actions).toMatchObject([
      { avatar_action_id: "action-1", pending_model_count: 0 },
    ]);
  });

  it("renames an action while preserving its media and preparation state", async () => {
    const root = await repositoryRoot();
    await createOwnedAvatar({ displayName: "Lin", sourceImageDataUrl: jpeg, avatarId: "avatar-123" }, root);
    await appendOwnedAvatarAction("avatar-123", {
      avatar_action_id: "action-1",
      display_name: "自然待机",
      video_url: "/api/avatar-assets/artifacts/a1",
      pending_model_count: 1,
    }, root);

    const renamed = await updateOwnedAvatarAction("avatar-123", "action-1", { displayName: "  温柔回应  " }, root);

    expect(renamed).toMatchObject({
      avatar_action_id: "action-1",
      display_name: "温柔回应",
      video_url: "/api/avatar-assets/artifacts/a1",
      pending_model_count: 1,
    });
    await expect(updateOwnedAvatarAction("avatar-123", "action-1", { displayName: "   " }, root))
      .rejects.toThrow("请填写动作名称");
  });

  it("replaces the source image, clears the realtime binding, and trashes active actions on request", async () => {
    const root = await repositoryRoot();
    await createOwnedAvatar({ displayName: "Lin", sourceImageDataUrl: jpeg, avatarId: "avatar-123" }, root);
    await appendOwnedAvatarAction("avatar-123", {
      avatar_action_id: "action-1",
      display_name: "自然待机",
      video_url: "/api/avatar-assets/artifacts/a1",
    }, root);
    await updateOwnedAvatar("avatar-123", {
      realtimeBinding: {
        avatar_id: "avatar-123",
        provider: "anam",
        provider_avatar_id: "anam-old-face",
        avatar_model: "cara-4",
        state: "accepted",
        preview_video_url: null,
      },
    }, root);

    const avatar = await replaceOwnedAvatarSourceImage("avatar-123", {
      sourceImageDataUrl: png,
      trashActions: true,
    }, root);

    expect(avatar.realtime_binding).toBeNull();
    expect(avatar.actions[0].deleted_at).toBeTruthy();
    expect((await readOwnedAvatarImage("avatar-123", root))?.mediaType).toBe("image/png");
    expect((await readOwnedAvatarImage("avatar-123", root))?.bytes).toEqual(pngBytes);
  });

  it("keeps existing actions when replacing the source image without trashing them", async () => {
    const root = await repositoryRoot();
    await createOwnedAvatar({ displayName: "Lin", sourceImageDataUrl: jpeg, avatarId: "avatar-123" }, root);
    await appendOwnedAvatarAction("avatar-123", {
      avatar_action_id: "action-1",
      display_name: "自然待机",
      video_url: null,
    }, root);

    const avatar = await replaceOwnedAvatarSourceImage("avatar-123", {
      sourceImageDataUrl: png,
      trashActions: false,
    }, root);

    expect(avatar.actions[0].deleted_at).toBeNull();
  });

  it("reuses an internal preset as the canonical Avatar aggregate", async () => {
    const root = await repositoryRoot();
    const first = await createOwnedAvatar({
      displayName: "陪伴",
      sourceImageDataUrl: jpeg,
      avatarId: "companion",
    }, root);
    const repeated = await createOwnedAvatar({
      displayName: "陪伴",
      sourceImageDataUrl: jpeg,
      avatarId: "companion",
    }, root);
    await appendOwnedAvatarAction("companion", {
      avatar_action_id: "action-smile",
      display_name: "亲和微笑",
      video_url: "/api/avatar-assets/artifacts/smile",
    }, root);

    expect(first.avatar_id).toBe("companion");
    expect(repeated.avatar_id).toBe("companion");
    expect(await listOwnedAvatars(root)).toMatchObject([{
      avatar_id: "companion",
      actions: [{ avatar_action_id: "action-smile", display_name: "亲和微笑" }],
    }]);
  });

  it("soft-deletes and restores an Avatar for the 30-day recycle bin", async () => {
    const root = await repositoryRoot();
    await createOwnedAvatar({ displayName: "Lin", sourceImageDataUrl: jpeg, avatarId: "avatar-123" }, root);
    await updateOwnedAvatar("avatar-123", { deletedAt: "2026-08-28T00:00:00.000Z" }, root);
    expect((await findOwnedAvatar("avatar-123", root))?.deleted_at).toBe("2026-08-28T00:00:00.000Z");
    await updateOwnedAvatar("avatar-123", { deletedAt: null }, root);
    expect((await findOwnedAvatar("avatar-123", root))?.deleted_at).toBeNull();
  });

  it("renames an Avatar without changing its identity or assets", async () => {
    const root = await repositoryRoot();
    await createOwnedAvatar({ displayName: "Lin", sourceImageDataUrl: jpeg, avatarId: "avatar-123" }, root);
    await appendOwnedAvatarAction("avatar-123", {
      avatar_action_id: "action-1",
      display_name: "自然待机",
      video_url: "/api/avatar-assets/artifacts/a1",
    }, root);

    const renamed = await updateOwnedAvatar("avatar-123", { displayName: "  小林  " }, root);

    expect(renamed).toMatchObject({
      avatar_id: "avatar-123",
      display_name: "小林",
      actions: [{ avatar_action_id: "action-1", video_url: "/api/avatar-assets/artifacts/a1" }],
    });
    await expect(updateOwnedAvatar("avatar-123", { displayName: "   " }, root))
      .rejects.toThrow("请填写 Avatar 名称");
  });

  it("purges expired actions while keeping their Avatar", async () => {
    const root = await repositoryRoot();
    await createOwnedAvatar({ displayName: "Lin", sourceImageDataUrl: jpeg, avatarId: "avatar-123" }, root);
    await appendOwnedAvatarAction("avatar-123", {
      avatar_action_id: "action-1",
      display_name: "旧动作",
      video_url: null,
    }, root);
    await updateOwnedAvatarAction("avatar-123", "action-1", { deletedAt: "2020-01-01T00:00:00.000Z" }, root);

    expect(await listOwnedAvatars(root)).toMatchObject([{ avatar_id: "avatar-123", actions: [] }]);
  });
});

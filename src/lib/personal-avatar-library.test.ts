import { afterEach, describe, expect, it } from "vitest";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { attachPersonalMotionToAvatar, attachPersonalTalkingVariant, createPersonalAvatar, findPersonalAvatar, listPersonalAvatars, renamePersonalAvatar, updatePersonalAvatarAction, updatePersonalTalkingVariant } from "./personal-avatar-library";
import { savePersonalMotion } from "./personal-motion-library";

let temporary = "";
const originalPath = process.env.OPENREALTIME_PERSONAL_MOTION_PATH;
afterEach(async () => {
  if (originalPath === undefined) delete process.env.OPENREALTIME_PERSONAL_MOTION_PATH;
  else process.env.OPENREALTIME_PERSONAL_MOTION_PATH = originalPath;
  if (temporary) await rm(temporary, { recursive: true, force: true });
  temporary = "";
});

describe("personal avatar talking material", () => {
  it("saves a Lip Forcing variant only under the owner's matching action", async () => {
    temporary = await mkdtemp(path.join(os.tmpdir(), "personal-avatar-"));
    process.env.OPENREALTIME_PERSONAL_MOTION_PATH = temporary;
    const alice = { issuer: "test", subject: "alice" };
    const bob = { issuer: "test", subject: "bob" };
    const image = new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]);
    const avatar = await createPersonalAvatar(alice, "测试形象", "image/png", image);
    expect(avatar.source_image_url).toMatch(new RegExp(`^/api/user/avatars/${avatar.avatar_id}/image\\?v=`));
    const motion = await savePersonalMotion(alice, "task-123456", "Wave", 4, new Uint8Array([0, 0, 0, 24, 102, 116, 121, 112]));
    const action = await attachPersonalMotionToAvatar(alice, avatar.avatar_id, motion.id);
    const variant = { id: "lipforcing-123", display_name: "讲话", method: "lipforcing" as const,
      source_video_url: action.video_url!, video_url: "/api/user/avatars/private/video", processing: "original" as const,
      validation: "pending" as const };
    await expect(attachPersonalTalkingVariant(alice, avatar.avatar_id, action.avatar_action_id, { ...variant, source_video_url: "/wrong.mp4" })).rejects.toThrow("动作底片已变更");
    const updated = await attachPersonalTalkingVariant(alice, avatar.avatar_id, action.avatar_action_id, variant);
    expect(updated.talking_variants).toEqual([variant]);
    expect((await findPersonalAvatar(alice, avatar.avatar_id))?.actions[0].talking_variants).toEqual([variant]);
    expect(await listPersonalAvatars(bob)).toEqual([]);
    await expect(attachPersonalTalkingVariant(bob, avatar.avatar_id, action.avatar_action_id, variant)).rejects.toThrow("动作底片已变更");
  });

  it("renames personal avatars, actions, and talking materials without changing their IDs", async () => {
    temporary = await mkdtemp(path.join(os.tmpdir(), "personal-avatar-management-"));
    process.env.OPENREALTIME_PERSONAL_MOTION_PATH = temporary;
    const user = { issuer: "test", subject: "owner" };
    const image = new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]);
    const avatar = await createPersonalAvatar(user, "旧形象", "image/png", image);
    const motion = await savePersonalMotion(user, "task-management", "旧动作", 4, new Uint8Array([0, 0, 0, 24, 102, 116, 121, 112]));
    const action = await attachPersonalMotionToAvatar(user, avatar.avatar_id, motion.id);
    const variant = { id: "lipforcing-manage", display_name: "旧口型对齐", method: "lipforcing" as const,
      source_video_url: action.video_url!, video_url: "/api/user/avatars/private/video", processing: "original" as const,
      validation: "pending" as const };
    await attachPersonalTalkingVariant(user, avatar.avatar_id, action.avatar_action_id, variant);

    const renamedAvatar = await renamePersonalAvatar(user, avatar.avatar_id, "新形象");
    const renamedAction = await updatePersonalAvatarAction(user, avatar.avatar_id, action.avatar_action_id, { displayName: "新动作" });
    const renamedVariantAction = await updatePersonalTalkingVariant(user, avatar.avatar_id, action.avatar_action_id, variant.id, { displayName: "新口型对齐" });

    expect(renamedAvatar).toMatchObject({ avatar_id: avatar.avatar_id, display_name: "新形象" });
    expect(renamedAction).toMatchObject({ avatar_action_id: action.avatar_action_id, display_name: "新动作" });
    expect(renamedVariantAction.talking_variants?.[0]).toMatchObject({ id: variant.id, display_name: "新口型对齐" });
    expect((await findPersonalAvatar(user, avatar.avatar_id))?.actions[0]).toMatchObject({ display_name: "新动作" });
  });
});

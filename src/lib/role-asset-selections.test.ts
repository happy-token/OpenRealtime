import { describe, expect, it } from "vitest";
import type { OwnedAvatarRecord } from "./avatar-records";
import { cleanRoleAssetDefaults, validRoleAssetSelection } from "./role-asset-selections";
const avatar: OwnedAvatarRecord = { avatar_id: "avatar-test", display_name: "形象", source_image_url: "/image", created_at: "", updated_at: "", deleted_at: null, realtime_binding: null, actions: [{ avatar_action_id: "action-test", display_name: "底片", video_url: "/base", pending_model_count: 0, created_at: "", deleted_at: null, talking_variants: [{ id: "variant-test", display_name: "口型", method: "lipforcing", source_video_url: "/base", video_url: "/talking", processing: "original", validation: "pending" }] }] };
const selections = { motion: { action_id: "action-test" }, "lip-sync": { action_id: "action-test" }, offline: { action_id: "action-test", talking_variant_id: "variant-test" }, realtime: { avatar_id: "remote-test" } };
describe("role asset deletion reconciliation", () => {
  it("clears the base and its paired selection when the base is deleted", () => {
    const deleted = structuredClone(avatar); deleted.actions[0].deleted_at = "today";
    expect(validRoleAssetSelection(deleted, "action-test", "variant-test")).toEqual({ actionId: null, variantId: null });
    expect(cleanRoleAssetDefaults(deleted, selections)).toEqual({ realtime: selections.realtime });
  });
  it("keeps the base after deleting a variant and clears only offline defaults", () => {
    const deleted = structuredClone(avatar); deleted.actions[0].talking_variants![0].deleted_at = "today";
    expect(validRoleAssetSelection(deleted, "action-test", "variant-test")).toEqual({ actionId: "action-test", variantId: null });
    expect(cleanRoleAssetDefaults(deleted, selections)).toEqual({ motion: selections.motion, "lip-sync": selections["lip-sync"], realtime: selections.realtime });
  });
  it("rejects variants paired with an older base", () => {
    const changed = structuredClone(avatar); changed.actions[0].video_url = "/new-base";
    expect(validRoleAssetSelection(changed, "action-test", "variant-test").variantId).toBeNull();
  });
  it("removes all local defaults when a shape is deleted, without removing independent hosted realtime", () => {
    expect(cleanRoleAssetDefaults({ ...avatar, deleted_at: "today" }, selections)).toEqual({ realtime: selections.realtime });
  });
  it("preserves the chosen material on a rename and does not auto-select a restored material", () => {
    expect(validRoleAssetSelection({ ...avatar, display_name: "新名称" }, "action-test", "variant-test")).toEqual({ actionId: "action-test", variantId: "variant-test" });
    expect(validRoleAssetSelection(avatar, null, null)).toEqual({ actionId: null, variantId: null });
  });
});

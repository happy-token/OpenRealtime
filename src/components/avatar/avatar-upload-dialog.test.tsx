import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { DEFAULT_AVATAR_DISPLAY_CONFIG } from "@/components/digital-human/types";
import { createdAvatarDisplayConfig, displayNameFromImageFile } from "./avatar-upload-dialog";

describe("avatar upload dialog", () => {
  it("uses the uploaded filename as a friendly default name", () => {
    expect(displayNameFromImageFile("portrait.final.png")).toBe("portrait.final");
    expect(displayNameFromImageFile(".png")).toBe("新形象");
  });

  it("selects the new avatar and clears its action filmstrip", () => {
    expect(createdAvatarDisplayConfig(DEFAULT_AVATAR_DISPLAY_CONFIG, {
      avatar_id: "avatar-new",
      display_name: "我的新形象",
      source_image_url: "/api/avatar-assets/avatar-new",
      created_at: "2026-09-25T00:00:00.000Z",
      updated_at: "2026-09-25T00:00:00.000Z",
      deleted_at: null,
      realtime_binding: null,
      actions: [],
    })).toMatchObject({
      renderPath: "segmented",
      segmentedAvatarId: "avatar-new",
      segmentedDisplayName: "我的新形象",
      segmentedAvatarActionId: "",
      motionTalkingVariantId: "",
    });
  });

  it("inherits the global liquid-glass transparency and blur variables", () => {
    const css = readFileSync(new URL("./avatar-upload-dialog.module.css", import.meta.url), "utf8");
    const productionCss = readFileSync(new URL("./avatar-production-overlay.module.css", import.meta.url), "utf8");
    expect(css).toContain("var(--panel-surface-alpha");
    expect(css).toContain("var(--panel-highlight-alpha");
    expect(css).toContain("blur(var(--panel-blur");
    expect(productionCss).toContain("var(--panel-surface-alpha");
    expect(productionCss).toContain("var(--panel-highlight-alpha");
    expect(productionCss).toContain("blur(var(--panel-blur");
    expect(productionCss).not.toMatch(/blur\(\d+px\)/);
  });

  it("shares the upload window with real-time creation and requires preview confirmation", () => {
    const dialog = readFileSync(new URL("./avatar-upload-dialog.tsx", import.meta.url), "utf8");
    const resourceHome = readFileSync(new URL("./avatar-resource-home.tsx", import.meta.url), "utf8");
    const realtimeLibrary = readFileSync(new URL("../workspace/resource-library-screen.tsx", import.meta.url), "utf8");
    expect(dialog).toContain('mode?: "avatar" | "realtime"');
    expect(dialog).toContain('"确认效果并启用"');
    expect(dialog).toContain("acceptOwnedAvatarRealtimeBinding");
    expect(resourceHome).toContain('task === "avatar" || task === "realtime" ? <AvatarUploadDialog');
    expect(realtimeLibrary).toContain('<AvatarUploadDialog');
    expect(realtimeLibrary).toContain('mode="realtime"');
  });
});

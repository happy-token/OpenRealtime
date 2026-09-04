import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { AvatarAsset } from "@/lib/avatar-catalog";
import { AvatarAssetLibrary, shouldAutoAdvanceAvatarCardMedia } from "./avatar-asset-library";
import { AvatarLibraryScreen } from "./avatar-library-screen";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
}));

const privateAvatar: AvatarAsset = {
  avatarId: "avatar-lin",
  displayName: "Lin",
  ownerId: "user-1",
  visibility: "private",
  source: { kind: "owned", imageUrl: "/lin.png" },
  actions: [{
    avatarActionId: "action-idle",
    displayName: "自然待机",
    state: "available",
    videoUrl: "/idle.mp4",
    pendingModelCount: 0,
  }],
  realtimeBinding: {
    providerAvatarId: "anam-lin",
    provider: "anam",
    avatarModel: "cara-4",
    state: "accepted",
    previewVideoUrl: null,
  },
  canCreateActions: true,
  deletedAt: null,
};

const internalPresetAvatar: AvatarAsset = {
  avatarId: "companion",
  displayName: "陪伴",
  ownerId: null,
  visibility: "shared",
  source: { kind: "owned", imageUrl: "/digital-human/opentalking/companion/reference.png" },
  actions: [{
    avatarActionId: "builtin:opentalking:companion",
    displayName: "陪伴 · 内置动作",
    state: "available",
    videoUrl: "/digital-human/opentalking/companion/motion.mp4",
    pendingModelCount: 0,
  }],
  realtimeBinding: null,
  canCreateActions: true,
  deletedAt: null,
};

const builtInAvatar: AvatarAsset = {
  avatarId: "avatar-stock-liv",
  displayName: "Liv",
  ownerId: null,
  visibility: "shared",
  source: { kind: "provider-preview", imageUrl: "https://provider.invalid/liv.png" },
  actions: [],
  realtimeBinding: {
    providerAvatarId: "anam-stock-liv",
    provider: "anam",
    avatarModel: "cara-3",
    state: "accepted",
    previewVideoUrl: null,
  },
  canCreateActions: false,
  deletedAt: null,
};

const localSegmentedAvatar: AvatarAsset = {
  ...privateAvatar,
  avatarId: "avatar-digital-human-1",
  displayName: "数字人1",
  realtimeBinding: null,
};

const unconfiguredOwnedAvatar: AvatarAsset = {
  ...localSegmentedAvatar,
  avatarId: "avatar-digital-human-2",
  displayName: "数字人2",
  actions: [],
};

describe("AvatarAssetLibrary", () => {
  it("keeps card titles directly on the media without a background strip", () => {
    const css = readFileSync(new URL("./avatar-asset-library.module.css", import.meta.url), "utf8");

    expect(css).toMatch(/\.titleRow\s*{[^}]*border:\s*0[^}]*background:\s*transparent[^}]*box-shadow:\s*none/s);
    expect(css).toMatch(/\.titleBlock\s*{[^}]*text-shadow:/s);
  });

  it("shows one stable loading state instead of a partial internal catalog", () => {
    const html = renderToStaticMarkup(
      <AvatarLibraryScreen initialScope="internal-preset" />,
    );

    expect(html).toContain('aria-busy="true"');
    expect(html).toContain("正在加载数字人资产");
    expect(html).not.toContain("内部预制形象 <em>1</em>");
  });

  it("opens realtime drive on the user's custom Avatars", () => {
    const html = renderToStaticMarkup(
      <AvatarAssetLibrary
        avatars={[privateAvatar, builtInAvatar, internalPresetAvatar]}
        internalPresetIds={["companion"]}
        initialScope="realtime"
      />,
    );

    expect(html).toContain("Lin");
    expect(html).toContain('data-scope="realtime"');
    expect(html).toContain('aria-pressed="true"');
    expect(html).not.toContain("可使用图片");
    expect(html).toContain("1 个动作");
    expect(html).toContain('href="/avatars/create?task=action&amp;avatar_id=avatar-lin"');
    expect(html).toContain('href="/?avatar_id=avatar-lin&amp;experience=avatar"');
    expect(html).not.toContain(">Liv<");
    expect(html).not.toContain(">陪伴<");
    expect(html).not.toContain("未配置");
  });

  it("separates official built-in realtime Avatars from custom ones", () => {
    const html = renderToStaticMarkup(
      <AvatarAssetLibrary
        avatars={[privateAvatar, builtInAvatar, internalPresetAvatar]}
        internalPresetIds={["companion"]}
        initialScope="realtime"
        initialRealtimeScope="built-in"
      />,
    );

    expect(html).toContain("Liv");
    expect(html).toContain("Anam 内置 · 仅实时驱动");
    expect(html).toContain('href="/?avatar_id=avatar-stock-liv&amp;experience=avatar"');
    expect(html).not.toContain(">Lin<");
    expect(html).not.toContain(">陪伴<");
    expect(html).not.toContain("/actions/create");
  });

  it("shows exactly the supplied internal presets in their own category", () => {
    const html = renderToStaticMarkup(
      <AvatarAssetLibrary
        avatars={[privateAvatar, builtInAvatar, internalPresetAvatar]}
        internalPresetIds={["companion"]}
        initialScope="internal-preset"
      />,
    );

    expect(html).toContain("陪伴");
    expect(html).toContain('data-scope="internal-preset"');
    expect(html).toContain('href="/?avatar_id=companion&amp;experience=avatar"');
    expect(html).toContain('aria-label="管理 陪伴 的 1 个动作"');
    expect(html).toContain("1 个动作");
    expect(html).toContain('href="/avatars/create?task=action&amp;avatar_id=companion"');
    expect(html).toContain('aria-label="删除形象：陪伴"');
    expect(html).toContain('href="/avatars/companion?return_scope=internal-preset"');
    expect(html).toContain('aria-label="查看 陪伴 详情"');
    expect(html).toContain('aria-label="更多操作：陪伴"');
    expect(html).not.toContain('aria-label="陪伴 形象与动作层叠浏览"');
    expect(html).not.toContain('data-size="compact"');
    expect(html).not.toContain("Internal Preset");
    expect(html).not.toContain("可使用图片");
    expect(html).not.toContain("浏览动作");
    expect(html).not.toContain("陪伴 · 内置动作");
    expect(html).not.toContain('src="/digital-human/opentalking/companion/motion.mp4"');
    expect(html).not.toContain(">Liv<");
    expect(html).not.toContain(">Lin<");
    expect(html).not.toContain("/actions/create");
  });

  it("shows a locally created action Avatar in the segmented asset category", () => {
    const html = renderToStaticMarkup(
      <AvatarAssetLibrary
        avatars={[privateAvatar, builtInAvatar, internalPresetAvatar, localSegmentedAvatar]}
        internalPresetIds={["companion"]}
        initialScope="internal-preset"
      />,
    );

    expect(html).toContain("数字人1");
    expect(html).toContain('href="/avatars/avatar-digital-human-1?return_scope=internal-preset"');
  });

  it("shows a locally created Avatar before it has actions or a realtime binding", () => {
    const html = renderToStaticMarkup(
      <AvatarAssetLibrary
        avatars={[unconfiguredOwnedAvatar]}
        internalPresetIds={["companion"]}
        initialScope="internal-preset"
      />,
    );

    expect(html).toContain("数字人2");
    expect(html).toContain('href="/avatars/avatar-digital-human-2?return_scope=internal-preset"');
  });

  it("shows the action count once on a locally created segmented Avatar", () => {
    const html = renderToStaticMarkup(
      <AvatarAssetLibrary
        avatars={[localSegmentedAvatar]}
        internalPresetIds={["companion"]}
        initialScope="internal-preset"
      />,
    );

    expect(html.match(/1 个动作/g)).toHaveLength(1);
  });

  it("only shows the current media label when an action is active", () => {
    const html = renderToStaticMarkup(
      <AvatarAssetLibrary
        avatars={[internalPresetAvatar, localSegmentedAvatar]}
        internalPresetIds={["companion"]}
        initialScope="internal-preset"
      />,
    );

    expect(html).not.toContain("形象预览");
  });

  it("auto advances media for a locally created segmented Avatar", () => {
    expect(["companion"].includes(localSegmentedAvatar.avatarId)).toBe(false);
    expect(shouldAutoAdvanceAvatarCardMedia({
      segmentedAsset: true,
      expanded: false,
      previewingAction: false,
      menuOpen: false,
      playableActionCount: localSegmentedAvatar.actions.length,
    })).toBe(true);
  });
});

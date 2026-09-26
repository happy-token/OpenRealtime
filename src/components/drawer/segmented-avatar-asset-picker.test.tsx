import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { AvatarAsset } from "@/lib/avatar-catalog";
import { SegmentedAvatarAssetPicker, shouldAutoAdvanceSegmentedAvatarCardMedia } from "./segmented-avatar-asset-picker";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
}));

const localSegmentedAvatar: AvatarAsset = {
  avatarId: "avatar-digital-human-1",
  displayName: "数字人1",
  ownerId: "local-user",
  visibility: "private",
  source: { kind: "owned", imageUrl: "/api/avatars/avatar-digital-human-1/image" },
  actions: [{
    avatarActionId: "action-smile",
    displayName: "侧头微笑",
    state: "processing",
    videoUrl: "/api/avatar-assets/artifacts/action-smile",
    pendingModelCount: 1,
  }],
  realtimeBinding: null,
  canCreateActions: true,
  deletedAt: null,
};

const actionlessAvatar: AvatarAsset = {
  ...localSegmentedAvatar,
  avatarId: "avatar-digital-human-2",
  displayName: "数字人2",
  source: { kind: "owned", imageUrl: "/api/avatars/avatar-digital-human-2/image" },
  actions: [],
};

describe("SegmentedAvatarAssetPicker", () => {
  it("shows a locally created Avatar while its saved action is still being prepared", () => {
    const html = renderToStaticMarkup(
      <SegmentedAvatarAssetPicker
        avatars={[localSegmentedAvatar]}
        selectedAvatarId=""
        selectedActionId=""
        disabled={false}
        active={false}
        onSelect={() => {}}
      />,
    );

    expect(html).toContain("数字人1");
    expect(html).toContain('aria-label="数字人1 形象与动作"');
    expect(html).toContain("1 个动作");
    expect(html).toContain("查看形象与动作");
    expect(html).toContain('href="/resources?tab=avatars&amp;scope=internal-preset"');
    expect(html).not.toContain('href="/avatars/avatar-digital-human-1"');
    expect(html).toContain('aria-label="更多操作：数字人1"');
    expect(html).toContain('aria-label="浏览 数字人1 的形象与动作"');
    expect(html).not.toContain("segmented-avatar-card-kind");
  });

  it("auto advances shape and action previews only while the collapsed card is active", () => {
    expect(shouldAutoAdvanceSegmentedAvatarCardMedia({ focused: false, active: true, menuOpen: false, manuallyPaused: false, selected: false, playableActionCount: 1 })).toBe(true);
    expect(shouldAutoAdvanceSegmentedAvatarCardMedia({ focused: true, active: true, menuOpen: false, manuallyPaused: false, selected: false, playableActionCount: 1 })).toBe(false);
    expect(shouldAutoAdvanceSegmentedAvatarCardMedia({ focused: false, active: true, menuOpen: true, manuallyPaused: false, selected: false, playableActionCount: 1 })).toBe(false);
    expect(shouldAutoAdvanceSegmentedAvatarCardMedia({ focused: false, active: true, menuOpen: false, manuallyPaused: true, selected: false, playableActionCount: 1 })).toBe(false);
    expect(shouldAutoAdvanceSegmentedAvatarCardMedia({ focused: false, active: true, menuOpen: false, manuallyPaused: false, selected: true, playableActionCount: 1 })).toBe(false);
  });

  it("shows and allows opening an owned Avatar before it has any actions", () => {
    const html = renderToStaticMarkup(
      <SegmentedAvatarAssetPicker
        avatars={[actionlessAvatar]}
        selectedAvatarId=""
        selectedActionId=""
        disabled={false}
        active={false}
        onSelect={() => {}}
      />,
    );

    expect(html).toContain('aria-label="数字人2 形象与动作"');
    expect(html).toContain('aria-label="展开 数字人2 的形象和动作"');
    expect(html).toContain('aria-label="确认使用形象：数字人2"');
    expect(html).not.toContain('aria-label="上一项：数字人2"');
    expect(html).toContain("未创建动作");
  });

  it("renders direct previous, next, and confirm controls on cards with actions", () => {
    const availableAvatar: AvatarAsset = {
      ...localSegmentedAvatar,
      actions: [{
        ...localSegmentedAvatar.actions[0],
        state: "available",
        pendingModelCount: 0,
      }],
    };
    const html = renderToStaticMarkup(
      <SegmentedAvatarAssetPicker
        avatars={[availableAvatar]}
        selectedAvatarId=""
        selectedActionId=""
        disabled={false}
        active={false}
        onSelect={() => {}}
      />,
    );

    expect(html).toContain('aria-label="上一项：数字人1"');
    expect(html).toContain('aria-label="下一项：数字人1"');
    expect(html).toContain('aria-label="确认使用形象：数字人1"');
    expect(html).toContain(">确认使用</button>");
  });
});

it("shows talking clips for owned avatars with realtime bindings and confirms the material itself", () => {
  const html = renderToStaticMarkup(<SegmentedAvatarAssetPicker
    actionsOnly avatars={[{ ...localSegmentedAvatar, realtimeBinding: { provider: "anam", providerAvatarId: "remote", avatarModel: "cara-3", state: "accepted", previewVideoUrl: null }, actions: [{ avatarActionId: "talking-id", displayName: "柔和回应 · MuseTalk", state: "available", videoUrl: "/talking.mp4", pendingModelCount: 0 }] }]}
    selectedAvatarId="" selectedActionId="" disabled={false} active onSelect={() => {}}
  />);
  expect(html).toContain('src="/talking.mp4"');
  expect(html).toContain('aria-label="确认使用口型对齐：柔和回应 · MuseTalk"');
  expect(html).toContain('data-actions-only="true"');
  expect(html).toContain("1 个口型对齐");
});

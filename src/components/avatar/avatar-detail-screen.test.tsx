import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import {
  ActionDockPreview,
  AvatarAssetDeleteButton,
  AvatarActionRenameDialog,
  AvatarDetailScreen,
  AvatarPersonaStatus,
  AvatarSourceReplacementDialog,
  dedupeAvatarActionsByDisplayName,
  canDeleteAvatarAction,
  getAvatarActionDockWheelDelta,
  shouldPlayAvatarActionDockPreview,
  shouldAutoAdvanceAvatarDetailMedia,
} from "./avatar-detail-screen";

describe("AvatarPersonaStatus", () => {
  it("renders nothing before the Persona lookup settles", () => {
    const html = renderToStaticMarkup(<AvatarPersonaStatus
      avatarId="avatar-zhaoning"
      avatarName="昭宁"
      realtimeBound={false}
      linkedPersonaName={null}
      personaChecked={false}
    />);
    expect(html).toBe("");
  });

  it("shows a 关联 Persona CTA linking to /personas once an unlinked Avatar is checked", () => {
    const html = renderToStaticMarkup(<AvatarPersonaStatus
      avatarId="avatar-zhaoning"
      avatarName="昭宁"
      realtimeBound={false}
      linkedPersonaName={null}
      personaChecked
    />);
    expect(html).toContain("未关联 Persona");
    expect(html).toContain(`href="/personas?avatar_id=avatar-zhaoning&amp;avatar_display_name=%E6%98%AD%E5%AE%81"`);
    expect(html).toContain("关联 Persona");
  });

  it("retargets 更换 to /personas for an Avatar with a linked Persona", () => {
    const html = renderToStaticMarkup(<AvatarPersonaStatus
      avatarId="avatar-zhaoning"
      avatarName="昭宁"
      realtimeBound={false}
      linkedPersonaName="知性温柔"
      personaChecked
    />);
    expect(html).toContain("默认 Persona：知性温柔");
    expect(html).toContain(`href="/personas?avatar_id=avatar-zhaoning&amp;avatar_display_name=%E6%98%AD%E5%AE%81"`);
    expect(html).toContain("更换");
    expect(html).not.toContain("open_config=model");
  });
});

describe("AvatarDetailScreen", () => {
  it("keeps image-only Avatars conversational and invites action creation", () => {
    const html = renderToStaticMarkup(<AvatarDetailScreen avatarId="avatar-123" />);
    expect(html).toContain("开始对话");
    expect(html).toContain("尚未创建动作");
    expect(html).toContain("创建动作");
    expect(html).not.toContain("未配置");
    expect(html).not.toContain(">图片可用<");
    expect(html).not.toContain("Avatar / Immersive Detail");
    expect(html).not.toContain("Avatar Source");
    expect(html).toContain("技术信息");
    expect(html.indexOf('id="avatar-detail-title"')).toBeLessThan(html.indexOf("尚未创建动作"));
    expect(html.indexOf("尚未创建动作")).toBeLessThan(html.indexOf("开始对话"));
  });

  it("explains binding cleanup and lets the user choose whether to trash old actions", () => {
    const html = renderToStaticMarkup(<AvatarSourceReplacementDialog
      avatarName="Lin"
      fileName="new-face.png"
      previewImageUrl="data:image/png;base64,iVBORw0KGgo="
      actionCount={2}
      hasRealtimeBinding
      trashActions
      busy={false}
      error=""
      onTrashActionsChange={() => {}}
      onCancel={() => {}}
      onConfirm={() => {}}
    />);

    expect(html).toContain("更换“Lin”的形象图片？");
    expect(html).toContain("实时绑定将自动解除");
    expect(html).toContain("Anam 远端形象不会被删除");
    expect(html).toContain("将 2 个旧动作移入回收站");
    expect(html).toContain('type="checkbox" checked=""');
  });

  it("renders an action rename dialog without implying video regeneration", () => {
    const html = renderToStaticMarkup(<AvatarActionRenameDialog
      actionName="自然待机"
      value="自然回应"
      busy={false}
      error=""
      onValueChange={() => {}}
      onCancel={() => {}}
      onSubmit={() => {}}
    />);

    expect(html).toContain("修改动作名称");
    expect(html).toContain('aria-label="新的动作名称"');
    expect(html).toContain("不会重新生成视频或影响口型模型");
    expect(html).toContain("保存名称");
  });

  it("renders a digital-human rename dialog without implying asset replacement", () => {
    const html = renderToStaticMarkup(<AvatarActionRenameDialog
      assetKind="avatar"
      actionName="数字人1"
      value="数字人一号"
      busy={false}
      error=""
      onValueChange={() => {}}
      onCancel={() => {}}
      onSubmit={() => {}}
    />);

    expect(html).toContain("修改数字人名称");
    expect(html).toContain('aria-label="新的数字人名称"');
    expect(html).toContain("不会改变数字人 ID、形象图片、动作或模型");
  });

  it("uses the Avatar image as a nonblank action-card poster and defers offscreen loading", () => {
    const idle = renderToStaticMarkup(<ActionDockPreview
      src="/action.mp4"
      poster="/avatar.webp"
      label="动作缩略预览"
      playing={false}
    />);

    expect(idle).toContain('poster="/avatar.webp"');
    expect(idle).toContain('preload="none"');
    expect(idle).toContain('data-playing="false"');
    expect(idle).toContain('data-ambient-visible="false"');
    expect(idle).not.toContain("autoPlay");
  });

  it("plays engaged or visible action cards only while the page is visible", () => {
    expect(shouldPlayAvatarActionDockPreview({ engaged: false, withinViewport: false, ambientPlaybackReady: false, pageVisible: true })).toBe(false);
    expect(shouldPlayAvatarActionDockPreview({ engaged: false, withinViewport: true, ambientPlaybackReady: true, pageVisible: true })).toBe(true);
    expect(shouldPlayAvatarActionDockPreview({ engaged: true, withinViewport: true, ambientPlaybackReady: false, pageVisible: true })).toBe(true);
    expect(shouldPlayAvatarActionDockPreview({ engaged: true, withinViewport: false, ambientPlaybackReady: true, pageVisible: true })).toBe(false);
    expect(shouldPlayAvatarActionDockPreview({ engaged: true, withinViewport: true, ambientPlaybackReady: true, pageVisible: false })).toBe(false);
  });

  it("only exposes deletion for the selected owned action", () => {
    expect(canDeleteAvatarAction(["action-1"], "action-1")).toBe(true);
    expect(canDeleteAvatarAction(["action-1"], "action-2")).toBe(false);
    expect(canDeleteAvatarAction(["action-1"], null)).toBe(false);
  });

  it("labels the owned Avatar deletion action clearly", () => {
    const html = renderToStaticMarkup(<AvatarAssetDeleteButton
      avatarName="数字人2"
      busy={false}
      onDelete={() => {}}
    />);

    expect(html).toContain("<span>删除</span>");
    expect(html).toContain('aria-label="删除数字人资产：数字人2"');
    expect(html).toContain("将数字人资产移入回收站");
  });

  it("maps the dominant mouse-wheel axis to horizontal action-list scrolling", () => {
    expect(getAvatarActionDockWheelDelta(0, 120)).toBe(120);
    expect(getAvatarActionDockWheelDelta(-80, 12)).toBe(-80);
  });

  it("pauses automatic switching for hover, focus, manual selection, or an unready stage video", () => {
    const ready = {
      hasAvatar: true,
      actionCount: 2,
      pageVisible: true,
      autoAdvancePinned: false,
      dockHovered: false,
      dockFocused: false,
      activeActionId: null,
      activeActionVideoUrl: null,
      readyStageActionId: null,
    };
    expect(shouldAutoAdvanceAvatarDetailMedia(ready)).toBe(true);
    expect(shouldAutoAdvanceAvatarDetailMedia({ ...ready, dockHovered: true })).toBe(false);
    expect(shouldAutoAdvanceAvatarDetailMedia({ ...ready, dockFocused: true })).toBe(false);
    expect(shouldAutoAdvanceAvatarDetailMedia({ ...ready, autoAdvancePinned: true })).toBe(false);
    expect(shouldAutoAdvanceAvatarDetailMedia({
      ...ready,
      activeActionId: "action-1",
      activeActionVideoUrl: "/action.mp4",
    })).toBe(false);
    expect(shouldAutoAdvanceAvatarDetailMedia({
      ...ready,
      activeActionId: "action-1",
      activeActionVideoUrl: "/action.mp4",
      readyStageActionId: "action-1",
    })).toBe(true);
  });

  it("deduplicates action lists by normalized display name", () => {
    const actions = dedupeAvatarActionsByDisplayName([
      {
        avatar_action_id: "catalog-1",
        display_name: "甜美元气",
        video_url: null,
        pending_model_count: 0,
        created_at: "2026-01-01T00:00:00.000Z",
        deleted_at: null,
      },
      {
        avatar_action_id: "owned-1",
        display_name: "  甜美元气  ",
        video_url: "/sweet.mp4",
        pending_model_count: 1,
        created_at: "2026-01-01T00:01:00.000Z",
        deleted_at: null,
      },
      {
        avatar_action_id: "other",
        display_name: "自然待机",
        video_url: "/idle.mp4",
        pending_model_count: 0,
        created_at: "2026-01-01T00:02:00.000Z",
        deleted_at: null,
      },
    ]);

    expect(actions).toHaveLength(2);
    expect(actions[0]?.avatar_action_id).toBe("owned-1");
    expect(actions[1]?.display_name).toBe("自然待机");
  });
});

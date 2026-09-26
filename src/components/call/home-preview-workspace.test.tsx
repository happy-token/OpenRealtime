import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { ProviderKeyGate } from "@/components/provider-key/provider-key-gate";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_AVATAR_DISPLAY_CONFIG } from "@/components/digital-human/types";
import { DEFAULT_TTS_VOICE } from "@/components/drawer/voice-options";
import { AVATAR_IDENTITY_DISPLAY_NAMES_STORAGE_KEY, CUSTOM_AVATAR_IDENTITY_STORAGE_KEY } from "@/lib/avatar-identity-sync";
import { MOTION_ASSET_METADATA_STORAGE_KEY } from "@/lib/digital-human-asset-management";
import { readDigitalHumanAssetCatalog } from "@/lib/digital-human-asset-catalog";
import type { RoleRecord } from "@/lib/role-records";
import type { OwnedAvatarRecord } from "@/lib/avatar-records";
import { HomeRoleModeControls } from "./home-role-mode-controls";
import {
  ActionMaterialFolder,
  buildSegmentedIdentityChoices,
  buildSegmentedMotionChoices,
  HomePreviewWorkspace,
  readAvatarMutationPayload,
  resolveMainAvatarMotionFit,
  resolveAvatarStagePreviewSource,
  resolveSelectedAvatarAction,
  resolveSegmentedHomePreview,
  shouldLoadAvatarPreviewDirectly,
} from "./home-preview-workspace";

const noop = vi.fn();

it("unmounts the GPU orb while the avatar preview is selected", () => {
  expect(renderHome("avatar")).not.toContain('aria-label="实时语音状态可视化"');
  expect(renderHome("voice")).toContain('aria-label="实时语音状态可视化"');
});

afterEach(() => vi.unstubAllGlobals());

describe("home action preview", () => {
  it("offers an expandable create-talking card for a library action with zero talking variants", () => {
    const html = renderAvatarLibraryHome();

    expect(html).not.toContain('aria-label="选择对话"');
    expect(html).toContain('aria-label="展开陪伴 · 内置动作的口型素材，共 0 个"');
    expect(html).toContain('aria-label="新建口型动作"');
    expect(html).not.toContain("当前动作还没有口型素材");
  });

  it("puts conversation before the role action folder and exposes its talking creation card", () => {
    const role: RoleRecord = {
      role_id: "role-sample", display_name: "测试角色", avatar_id: "avatar-sample", avatar_image_url: null,
      persona_id: null, persona_name: null, voice_provider: "bailian", voice_id: DEFAULT_TTS_VOICE,
      enabled_modes: ["conversation", "lip-sync", "offline"], default_mode: "conversation", default_selections: {},
      memory_enabled: false, tool_ids: [], created_at: "", updated_at: "", deleted_at: null,
    };
    const avatar = { avatar_id: "avatar-sample", source_image_url: "/avatar.png", actions: [{
      avatar_action_id: "action-sample", display_name: "挥手", video_url: "/motion.mp4", deleted_at: null,
      talking_variants: [
        { id: "lip-one", display_name: "预制口型", method: "lipforcing", video_url: "/lip.mp4", source_video_url: "/motion.mp4", deleted_at: null },
        { id: "muse-one", display_name: "其他口型", method: "musetalk", video_url: "/muse.mp4", source_video_url: "/motion.mp4", deleted_at: null },
      ],
    }] } as unknown as OwnedAvatarRecord;
    const html = renderToStaticMarkup(<HomeRoleModeControls role={role} mode="conversation" avatar={avatar}
      config={DEFAULT_AVATAR_DISPLAY_CONFIG} canStart runtimeLipSyncAvailable visualTheme="liquid-glass" themes={[]}
      onVisualThemeChange={noop} onModeSelect={async () => undefined} onStart={noop} />);

    expect(html.indexOf('aria-label="选择对话"')).toBeLessThan(html.indexOf('aria-label="展开挥手的口型动作'));
    expect(html).not.toContain('aria-label="选择实时口型：使用此底片"');
    expect(html).not.toContain('aria-label="选择预制口型：其他口型"');
    expect(html).toContain('aria-label="新建口型动作"');
    expect(html).not.toContain('aria-label="选择呈现方式"');

    const unavailableHtml = renderToStaticMarkup(<HomeRoleModeControls role={role} mode="conversation" avatar={avatar}
      config={DEFAULT_AVATAR_DISPLAY_CONFIG} canStart runtimeLipSyncAvailable={false} visualTheme="liquid-glass" themes={[]}
      onVisualThemeChange={noop} onModeSelect={async () => undefined} onStart={noop} />);
    expect(unavailableHtml).not.toContain('aria-label="选择实时口型：使用此底片"');
    expect(unavailableHtml).toContain('aria-label="选择口型动作：预制口型"');
  });

  it("keeps existing talking materials and a create card in the expanded action folder", () => {
    const html = renderToStaticMarkup(<ActionMaterialFolder
      action={{ avatarActionId: "action-smile", displayName: "微笑", videoUrl: "/smile.mp4", state: "available", pendingModelCount: 0 }}
      index={0}
      variants={[{ id: "talk-one", display_name: "口型一", method: "musetalk", source_video_url: "/smile.mp4", video_url: "/talk-one.mp4", processing: "original", validation: "pending" }]}
      selected
      open
      onOpenChange={noop}
      onSelectAction={noop}
      onSelectVariant={noop}
      onCreateTalking={noop}
    />);

    expect(html).toContain('aria-label="选择口型素材：口型一"');
    expect(html).toContain('aria-label="新建口型动作"');
    expect(html).toContain("新增口型对齐");
  });
  it("autoplays an action card even when another action or a talking variant is selected", () => {
    const html = renderToStaticMarkup(<ActionMaterialFolder
      action={{ avatarActionId: "action-smile", displayName: "微笑", videoUrl: "/smile.mp4", state: "available", pendingModelCount: 0 }}
      index={0} variants={[]} selected={false} selectedVariantId="talk-one" open={false}
      onOpenChange={noop} onSelectAction={noop} onSelectVariant={noop}
    />);

    expect(html).toMatch(/<video[^>]*aria-label="微笑 动作预览"[^>]*autoPlay=""[^>]*muted=""[^>]*loop=""/);
  });
  it("fills the stage height for landscape actions and preserves portrait actions", () => {
    expect(resolveMainAvatarMotionFit(1280, 720)).toBe("cover");
    expect(resolveMainAvatarMotionFit(720, 1280)).toBe("contain");
    expect(resolveMainAvatarMotionFit(0, 0)).toBe("contain");
  });

  it("keeps the selected action stable instead of switching preview media on a timer", () => {
    const component = readFileSync(new URL("./home-preview-workspace.tsx", import.meta.url), "utf8");

    expect(component).not.toMatch(/setTimeout\([^)]*setTalking|setTalking\(\(value\) => !value\)/s);
  });

  it("renders the selected action video instead of falling back to the static Avatar image", () => {
    const html = renderHome("avatar");

    expect(html).toContain('data-reduced-motion="true"');
    expect(html).toContain('aria-label="陪伴 动作预览"');
    expect(html).not.toContain('alt="陪伴 数字人预览"');
  });

  it("autoplays the selected base-motion card and the main stage in the library", () => {
    const html = renderAvatarLibraryHome();

    expect(html).toMatch(/<video[^>]*aria-label="陪伴 · 内置动作 动作预览"[^>]*autoPlay=""/);
    expect(html).toMatch(/<video[^>]*autoPlay=""[^>]*aria-label="陪伴 动作预览"/);
    expect(html).not.toContain('alt="陪伴 数字人预览"');
  });

  it("shows the selected talking variant on the library stage", () => {
    expect(resolveAvatarStagePreviewSource({
      libraryMode: true,
      avatarMode: "lip-sync",
      motionUrl: "/motion.mp4",
      talkingUrl: "/talking.mp4",
      force: null,
    })).toEqual({ url: "/talking.mp4", kind: "talking" });
  });
});

describe("resolveSegmentedHomePreview", () => {
  it("keeps the selected action video when the unified catalog only has the Avatar image", () => {
    const staticUnifiedChoice = {
      id: "segmented-identity:avatar-digital-human-1",
      name: "数字人1",
      role: "使用形象",
      preview: "/api/avatars/avatar-digital-human-1/image",
      config: DEFAULT_AVATAR_DISPLAY_CONFIG,
    };
    const actionChoice = {
      id: "segmented-motion:action-1",
      name: "数字人1动作",
      role: "配套动作",
      motion: "/api/avatar-assets/artifacts/action-1",
      config: DEFAULT_AVATAR_DISPLAY_CONFIG,
    };

    expect(resolveSegmentedHomePreview("motion", {
      unified: staticUnifiedChoice,
      motion: actionChoice,
      current: staticUnifiedChoice,
    })).toBe(actionChoice);
  });
});

describe("resolveSelectedAvatarAction", () => {
  it("prefers the owned video when a catalog action with the same id has no media URL", () => {
    expect(resolveSelectedAvatarAction({
      avatarActionId: "action-1",
      displayName: "待同步动作",
      videoUrl: "",
      state: "available",
      pendingModelCount: 0,
    }, {
      avatar_action_id: "action-1",
      display_name: "可播放动作",
      video_url: "/api/avatar-assets/artifacts/action-1",
      pending_model_count: 0,
      talking_variants: [],
      created_at: "2026-01-01T00:00:00.000Z",
      deleted_at: null,
    })).toMatchObject({
      avatarActionId: "action-1",
      displayName: "可播放动作",
      videoUrl: "/api/avatar-assets/artifacts/action-1",
    });
  });
});

describe("edge configuration affordances", () => {
  it("uses the shared liquid-glass material and hover reveal for both edge rails", () => {
    const css = readFileSync(new URL("./preview-workspace-lab.module.css", import.meta.url), "utf8");
    const component = readFileSync(new URL("./home-preview-workspace.tsx", import.meta.url), "utf8");
    const roleCss = readFileSync(new URL("./home-role-mode-controls.module.css", import.meta.url), "utf8");
    const roleComponent = readFileSync(new URL("./home-role-mode-controls.tsx", import.meta.url), "utf8");

    expect(css).toMatch(/\.edgeTrigger\s*\{[^}]*--edge-rail-surface:[^}]*var\(--panel-surface-alpha[^}]*backdrop-filter:\s*blur\(var\(--panel-blur/s);
    expect(css).toMatch(/\.edgeTrigger\[data-edge="right"\]\s*\{[^}]*width:\s*18px;[^}]*height:\s*112px/s);
    expect(css).toMatch(/\.edgeTrigger\[data-edge="bottom"\]\s*\{[^}]*width:\s*112px;[^}]*height:\s*18px/s);
    expect(css).toContain("transition: opacity 240ms ease, transform 260ms");
    expect(css).toMatch(/\.visualEdgePanel\[data-kind="media"\] \.visualEdgeList\s*\{[^}]*scrollbar-width:\s*thin/s);
    expect(css).toMatch(/\.actionEdgeList\s*\{[^}]*overflow-x:\s*auto[^}]*scrollbar-width:\s*thin/s);
    expect(css).toMatch(/\.visualEdgePanel,\.actionEdgePanel\s*\{[^}]*var\(--panel-highlight-alpha[^}]*var\(--panel-surface-alpha[^}]*blur\(var\(--panel-blur/s);
    expect(css).not.toMatch(/\.visualEdgePanel\[data-kind="media"\],\.actionEdgePanel\s*\{[^}]*background:\s*transparent/s);
    expect(component).toContain('onPointerEnter={() => openEdge("visual", "visual", !collapseResourceRails)}');
    expect(component).toContain('onPointerEnter={() => openEdge("motion", "action", !collapseResourceRails)}');
    expect(component).toContain("onPointerEnter={cancelEdgeClose}");
    expect(component).toContain("onPointerLeave={scheduleEdgeClose}");
    expect(roleCss).toMatch(/\.rightHandle,\.bottomHandle\s*\{[^}]*var\(--panel-surface-alpha[^}]*blur\(var\(--panel-blur/s);
    expect(roleCss).toMatch(/\.rolePanel,\.modePanel\s*\{[^}]*var\(--panel-highlight-alpha[^}]*var\(--panel-surface-alpha[^}]*blur\(var\(--panel-blur/s);
    expect(roleCss).not.toMatch(/\.controls:not\(\[data-open="none"\]\)[^{]*\{[^}]*pointer-events:\s*none/s);
    expect(roleComponent).toContain('onPointerEnter={() => openPanel("roles", true)}');
    expect(roleComponent).toContain('onPointerEnter={() => openPanel("modes", true)}');
    expect(roleComponent).toContain("onPointerLeave={schedulePanelClose}");
    expect(css).toMatch(/\.avatarPreviewForeground\s*\{[^}]*object-fit:\s*contain/s);
    expect(css).toMatch(/\.edgeMediaVisual > img\s*\{[^}]*object-fit:\s*contain/s);
    expect(roleCss).toMatch(/\.roleArtwork img\s*\{[^}]*object-fit:\s*contain/s);
    expect(roleCss).toMatch(/\.materialImage img\s*\{[^}]*object-fit:\s*contain/s);
    expect(css).toContain(".actionMaterialFolder");
  });
});

function renderHome(
  mode: "voice" | "avatar",
  connected = true,
  avatarConfig = mode === "avatar" ? {
    ...DEFAULT_AVATAR_DISPLAY_CONFIG,
    renderPath: "segmented" as const,
    segmentedPresetId: "custom-upload",
    segmentedAvatarId: "companion",
    segmentedAvatarActionId: "builtin:opentalking:companion",
  } : DEFAULT_AVATAR_DISPLAY_CONFIG,
) {
  return renderToStaticMarkup(
    <ProviderKeyGate>
      <HomePreviewWorkspace
      connected={connected}
      error={null}
      visualTheme="liquid-glass"
      experienceMode={mode}
      avatarDisplayConfig={avatarConfig}
      reducedMotion
      onVisualThemeChange={noop}
      onExperienceModeChange={noop}
      onAvatarDisplayConfigChange={noop}
      onStartSession={noop}
      />
    </ProviderKeyGate>,
  );
}

function renderAvatarLibraryHome(collapseResourceRails = false) {
  return renderToStaticMarkup(
    <ProviderKeyGate>
      <HomePreviewWorkspace
        purpose="library"
        connected
        error={null}
        visualTheme="liquid-glass"
        experienceMode="avatar"
        avatarDisplayConfig={{
          ...DEFAULT_AVATAR_DISPLAY_CONFIG,
          renderPath: "segmented",
          segmentedAvatarId: "companion",
          segmentedDisplayName: "陪伴",
          segmentedAvatarActionId: "builtin:opentalking:companion",
        }}
        reducedMotion
        onVisualThemeChange={noop}
        onExperienceModeChange={noop}
        onAvatarDisplayConfigChange={noop}
        onStartSession={noop}
        onOpenProduction={noop}
        collapseResourceRails={collapseResourceRails}
      />
    </ProviderKeyGate>,
  );
}

describe("HomePreviewWorkspace", () => {
  it("collapses both library rails during motion creation and restores them afterward", () => {
    const collapsed = renderAvatarLibraryHome(true);
    const restored = renderAvatarLibraryHome(false);
    const css = readFileSync(new URL("./preview-workspace-lab.module.css", import.meta.url), "utf8");

    expect(collapsed).toContain('data-resource-rails-collapsed="true"');
    expect(collapsed).toContain('aria-label="打开数字人形象" aria-expanded="false"');
    expect(collapsed).toContain('aria-label="打开动作列表" aria-expanded="false"');
    expect(collapsed).toMatch(/data-open="false"[^>]*aria-label="数字人形象" aria-hidden="true" inert=""/);
    expect(collapsed).toMatch(/aria-label="动作" aria-hidden="true" inert=""/);
    expect(collapsed).toMatch(/data-open="false"[^>]*aria-label="动作"/);
    expect(restored).toMatch(/data-open="true"[^>]*aria-label="数字人形象"/);
    expect(restored).toMatch(/data-open="true"[^>]*aria-label="动作"/);
    expect(css).toContain('.workspace[data-purpose="library"][data-resource-rails-collapsed="true"] .edgeTrigger[data-library="true"] { display: grid; }');
  });

  it("shows a newly generated motion directly on the library stage", () => {
    const html = renderToStaticMarkup(
      <ProviderKeyGate>
        <HomePreviewWorkspace
          purpose="library"
          connected
          error={null}
          visualTheme="liquid-glass"
          experienceMode="avatar"
          avatarDisplayConfig={DEFAULT_AVATAR_DISPLAY_CONFIG}
          reducedMotion
          stagePreview={{ url: "/generated-motion.mp4", name: "新动作" }}
          onVisualThemeChange={noop}
          onExperienceModeChange={noop}
          onAvatarDisplayConfigChange={noop}
          onStartSession={noop}
        />
      </ProviderKeyGate>,
    );

    expect(html).toContain('src="/generated-motion.mp4"');
    expect(html).toContain('aria-label="新动作 生成动作预览"');
    expect(html).toContain(">新动作</h1>");
  });

  it("reuses the home stage as the digital-human library without conversation controls", () => {
    const html = renderAvatarLibraryHome();

    expect(html).toContain('aria-label="数字人资产主页"');
    expect(html).toContain('aria-label="打开数字人形象"');
    expect(html).toContain('aria-label="打开动作列表"');
    expect(html).toContain('aria-label="创建形象"');
    expect(html).toContain('aria-label="创建动作"');
    expect(html).not.toContain('aria-label="主页开始对话"');
    expect(html).not.toContain('aria-label="Persona 快捷配置"');
  });

  it("keeps both library rails open and puts creation cards first", () => {
    const html = renderAvatarLibraryHome();
    const component = readFileSync(new URL("./home-preview-workspace.tsx", import.meta.url), "utf8");
    const css = readFileSync(new URL("./preview-workspace-lab.module.css", import.meta.url), "utf8");

    expect(html).toMatch(/data-open="true"[^>]*aria-label="数字人形象"/);
    expect(html).toMatch(/data-open="true"[^>]*aria-label="动作"/);
    expect(html.indexOf("创建形象")).toBeLessThan(html.indexOf("选择Shuchang"));
    expect(html.indexOf("创建动作")).toBeLessThan(html.indexOf("展开陪伴 · 内置动作的口型素材"));
    expect(component).not.toContain('eyebrow="实时形象"');
    expect(css).not.toContain("width: 216px");
    expect(css).toMatch(/\.workspace\[data-purpose="library"\] \.actionEdgePanel\s*\{[^}]*left:\s*calc\(var\(--workspace-sidebar-width,0px\) \+ 22px\)/s);
    expect(css).toMatch(/\.workspace :is\(\.visualEdgePanel\[data-kind="media"\],\.actionEdgePanel\)\s*\{[^}]*border:\s*0;[^}]*background:\s*transparent;[^}]*box-shadow:\s*none/s);
  });

  it("uses role selection and the compact mode drawer for a role session", () => {
    const role: RoleRecord = {
      role_id: "default-assistant", display_name: "默认助手", avatar_id: null, avatar_image_url: null,
      persona_id: null, persona_name: null, voice_provider: "bailian", voice_id: DEFAULT_TTS_VOICE,
      enabled_modes: ["conversation"], default_mode: "conversation", default_selections: {},
      memory_enabled: true, tool_ids: [], created_at: "2026-01-01T00:00:00.000Z",
      updated_at: "2026-01-01T00:00:00.000Z", deleted_at: null,
    };
    const html = renderToStaticMarkup(<ProviderKeyGate><HomePreviewWorkspace
      role={role} roleMode="conversation" onRoleSelect={noop} onRoleModeSelect={async () => undefined}
      connected error={null} visualTheme="cloud" experienceMode="voice"
      avatarDisplayConfig={DEFAULT_AVATAR_DISPLAY_CONFIG} reducedMotion onVisualThemeChange={noop} onExperienceModeChange={noop}
      onAvatarDisplayConfigChange={noop} onStartSession={noop}
    /></ProviderKeyGate>);
    expect(html).toContain('aria-label="角色列表"');
    expect(html).toContain('aria-label="模式与素材"');
    expect(html).toContain('aria-label="选择角色，当前默认助手"');
    expect(html).not.toContain('aria-label="数字人形象"');
  });
  it("keeps the selected owned Avatar visible while its catalog is loading", () => {
    const html = renderHome("avatar", true, {
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      renderPath: "segmented",
      segmentedPresetId: "avatar-8657be31-306e-428d-a013-7521e710ab6a",
      segmentedAvatarId: "avatar-8657be31-306e-428d-a013-7521e710ab6a",
      segmentedDisplayName: "数字人1",
      segmentedAvatarActionId: "338a867c-0661-4565-af6e-f0f2e0e9b3c7",
    });

    expect(html).toContain('alt="数字人1 数字人预览"');
    expect(html).toContain("与 数字人1 对话");
    expect(html).not.toContain("与 陪伴 对话");
  });

  it("loads protected local Avatar previews directly with the browser session", () => {
    expect(shouldLoadAvatarPreviewDirectly(
      "/api/avatars/avatar-8657be31-306e-428d-a013-7521e710ab6a/image",
    )).toBe(true);
    expect(shouldLoadAvatarPreviewDirectly(
      "/digital-human/opentalking/companion/preview.png",
    )).toBe(false);
  });

  it("turns non-JSON avatar mutation responses into a readable service error", async () => {
    await expect(readAvatarMutationPayload(new Response(
      "<!DOCTYPE html><html><body>Method Not Allowed</body></html>",
      { status: 405, headers: { "Content-Type": "text/html" } },
    ))).rejects.toThrow("数字人服务请求失败（HTTP 405）");
  });

  it("keeps conversation controls on the main stage without the old advanced drawer", () => {
    const html = renderHome("voice", true, DEFAULT_AVATAR_DISPLAY_CONFIG);

    expect(html).not.toContain("高级设置");
    expect(html).not.toContain(">呈现</span>");
    expect(html).not.toContain('aria-label="主页呈现模式"');
    expect(html).toContain('aria-label="主页开始对话"');
    expect(html).toContain('data-connection="ready"');
    expect(html).toContain("预览已就绪");
    expect(html).not.toContain("LIVE PREVIEW");
    expect(html).toContain('aria-label="Persona 快捷配置"');
    expect(html).not.toContain('aria-label="选择音色"');
    expect(html).toContain('aria-label="选择 Persona"');
    expect(html).not.toContain("configurationSummary");
    expect(html).toContain("voice-start-halo--magic-rings");
    expect(html).toContain('aria-label="视觉主题"');
    expect(html).toContain("液态玻璃");
    expect(html).toContain("调试面板");
    expect(html).toContain('data-theme="liquid-glass"');
    expect(html).toContain('data-theme="aurora-particles"');
    expect(html).toContain('data-theme="bars"');
    expect(html).toContain('aria-label="选择 Persona"');
    expect(html).toContain("未关联 Persona");
  });

  it("previews the selected runnable avatar before starting services", () => {
    const html = renderHome("avatar");

    expect(html).toContain("陪伴");
    expect(html).not.toContain('aria-label="主页呈现模式"');
    expect(html).toContain('aria-label="打开数字人形象"');
    expect(html).toContain('aria-label="打开动作列表"');
    expect(html).not.toContain('aria-label="打开口型对齐"');
    expect(html).not.toContain("LIP ALIGNMENT");
    expect(html).toContain('aria-label="选择陪伴"');
    expect(html).toContain('aria-label="陪伴 · 内置动作 动作预览"');
    expect(html).not.toContain("口型模型选择");
    expect(html).not.toContain("Wav2Lip 256");
    expect(html).toContain("与 陪伴 对话");
  });

  it("separates the independent avatar rail from the action rail", () => {
    const html = renderHome("avatar");

    expect(html).toContain('<aside');
    expect(html).toContain('aria-label="数字人形象"');
    expect(html).toContain('aria-label="动作"');
    expect(html).not.toContain('aria-label="口型对齐"');
  });

  it("shows only the two actual built-in Avatars before personal assets load", () => {
    const html = renderHome("avatar");
    const component = readFileSync(new URL("./home-preview-workspace.tsx", import.meta.url), "utf8");

    expect(html).toContain('aria-label="选择Shuchang"');
    expect(html).toContain('aria-label="选择陪伴"');
    expect(html).not.toContain('aria-label="选择职场女"');
    expect(html.match(/aria-label="选择(?:Shuchang|陪伴)"/g)).toHaveLength(2);
    expect(component).toContain("loadInternalPresetAvatars({ includeLocal: false })");
  });

  it("shows the same renamed, uploaded, and visible assets as the digital human workbench", () => {
    const customIdentityId = "custom-12345678-1234-4123-8123-123456789abc";
    const values = new Map<string, string>([
      [CUSTOM_AVATAR_IDENTITY_STORAGE_KEY, JSON.stringify({
        version: 2,
        selectedIdentityId: customIdentityId,
        identities: [{
          identityId: customIdentityId,
          name: "我的客服形象",
          dataUrl: "data:image/png;base64,customer",
          sourceSha256: "b".repeat(64),
          updatedAt: "2026-08-28T00:00:00.000Z",
        }],
      })],
      [AVATAR_IDENTITY_DISPLAY_NAMES_STORAGE_KEY, JSON.stringify({ companion: "小陪伴" })],
      [MOTION_ASSET_METADATA_STORAGE_KEY, JSON.stringify({
        version: 1,
        displayNames: { "builtin:opentalking:companion": "陪伴待机" },
        hiddenIds: ["builtin:opentalking:anchor"],
        hiddenIdentityIds: ["anchor"],
      })],
    ]);
    vi.stubGlobal("window", {
      location: { href: "http://localhost:3010/" },
      localStorage: { getItem: (key: string) => values.get(key) ?? null },
    });

    const catalog = readDigitalHumanAssetCatalog();
    const identities = buildSegmentedIdentityChoices(DEFAULT_AVATAR_DISPLAY_CONFIG, catalog);
    const motions = buildSegmentedMotionChoices(DEFAULT_AVATAR_DISPLAY_CONFIG, catalog);

    expect(identities).toEqual(expect.arrayContaining([
      expect.objectContaining({ name: "我的客服形象" }),
      expect.objectContaining({ name: "小陪伴" }),
    ]));
    expect(motions).toEqual(expect.arrayContaining([
      expect.objectContaining({ name: "陪伴待机" }),
      expect.objectContaining({
        id: "segmented-motion:builtin:shuchang-realtime-idle",
        name: "实时待机",
        motion: "/digital-human/builtin-motion/shuchang-realtime-idle.mp4",
      }),
    ]));
    expect([...identities, ...motions].some((choice) => choice.preview?.includes("/anchor/"))).toBe(false);
  });

  it("selects the realtime provider through the avatar instead of a provider control", () => {
    const html = renderHome("avatar", true, DEFAULT_AVATAR_DISPLAY_CONFIG);

    expect(html).not.toContain('aria-label="主页呈现模式"');
    expect(html).toContain('aria-label="数字人形象"');
    expect(html).toContain('href="/resources?tab=avatars"');
    expect(html).not.toContain("实时驱动供应商");
    expect(html).not.toContain("HeyGen");
    expect(html).not.toContain('aria-label="同步 Anam 数字人名称"');
  });

  it("keeps the start action disabled until the voice connection is ready", () => {
    const html = renderHome("voice", false);

    expect(html).toContain('data-connection="connecting"');
    expect(html).toContain("语音连接中");
    expect(html).toContain("开始语音对话");
    expect(html).not.toContain("语音服务准备中");
    expect(html).not.toContain(">正在连接</strong>");
    expect(html).toMatch(/<button[^>]*aria-label="主页开始对话"[^>]*disabled=""/);
  });

  it("uses sidebar settings instead of the old advanced settings launcher", () => {
    const html = renderHome("voice");

    expect(html).not.toContain('aria-label="打开高级设置"');
    expect(html).not.toContain('aria-label="高级设置"');
  });

  it("omits persona quick settings and the green return card for a hosted real-time avatar", () => {
    const html = renderToStaticMarkup(<ProviderKeyGate><HomePreviewWorkspace
      connected error={null} visualTheme="liquid-glass" experienceMode="avatar"
      avatarDisplayConfig={{ ...DEFAULT_AVATAR_DISPLAY_CONFIG, renderPath: "hosted", provider: "anam", avatarProfileId: "personal-one", hostedAvatarDisplayName: "我的数字人" }}
      officialRealtime reducedMotion onVisualThemeChange={noop} onExperienceModeChange={noop}
      onAvatarDisplayConfigChange={noop} onStartSession={noop}
    /></ProviderKeyGate>);
    expect(html).not.toContain("Persona 快捷配置");
    expect(html).not.toContain("返回实时数字人");
  });
});

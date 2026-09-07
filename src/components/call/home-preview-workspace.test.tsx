import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_AVATAR_DISPLAY_CONFIG } from "@/components/digital-human/types";
import { DEFAULT_TTS_VOICE } from "@/components/drawer/voice-options";
import { AVATAR_IDENTITY_DISPLAY_NAMES_STORAGE_KEY, CUSTOM_AVATAR_IDENTITY_STORAGE_KEY } from "@/lib/avatar-identity-sync";
import { MOTION_ASSET_METADATA_STORAGE_KEY } from "@/lib/digital-human-asset-management";
import { readDigitalHumanAssetCatalog } from "@/lib/digital-human-asset-catalog";
import {
  buildSegmentedIdentityChoices,
  buildSegmentedMotionChoices,
  HomePreviewWorkspace,
  readAvatarMutationPayload,
  resolveMainAvatarMotionFit,
  resolveSegmentedHomePreview,
  shouldLoadAvatarPreviewDirectly,
} from "./home-preview-workspace";

const noop = vi.fn();

it("unmounts the GPU orb while the avatar preview is selected", () => {
  expect(renderHome("avatar")).not.toContain('aria-label="实时语音状态可视化"');
  expect(renderHome("voice")).toContain('aria-label="实时语音状态可视化"');
});

afterEach(() => vi.unstubAllGlobals());

describe("resolveMainAvatarMotionFit", () => {
  it("fills the portrait main screen for landscape actions and preserves portrait actions", () => {
    expect(resolveMainAvatarMotionFit(1280, 720)).toBe("cover");
    expect(resolveMainAvatarMotionFit(720, 1280)).toBe("contain");
    expect(resolveMainAvatarMotionFit(0, 0)).toBe("contain");
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

describe("collapsed session settings button", () => {
  it("uses the selected liquid-orbit treatment without a status dot", () => {
    const css = readFileSync(new URL("./preview-workspace-lab.module.css", import.meta.url), "utf8");

    expect(css).toMatch(/\.liquidPanel\[data-state="collapsed"\]\s*{[^}]*width:\s*74px[^}]*height:\s*74px/s);
    expect(css).toMatch(/\.summaryIcon\s*{[^}]*width:\s*62px[^}]*height:\s*62px/s);
    expect(css).toMatch(/\.summaryIcon::before\s*{[^}]*inset:\s*-2px[^}]*animation:\s*settingsOrbitSpin 5s linear infinite/s);
    expect(css).toMatch(/\.summaryIcon::after\s*{[^}]*animation:\s*settingsOrbitSpin 3\.4s linear infinite reverse/s);
    expect(css).not.toContain("settingsStatusPulse");
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
  initialPanelState?: "collapsed" | "compact" | "expanded",
) {
  return renderToStaticMarkup(
    <HomePreviewWorkspace
      connected={connected}
      error={null}
      visualTheme="liquid-glass"
      experienceMode={mode}
      avatarDisplayConfig={avatarConfig}
      ttsProvider="bailian"
      ttsVoice={DEFAULT_TTS_VOICE}
      reducedMotion
      onVisualThemeChange={noop}
      onExperienceModeChange={noop}
      onAvatarDisplayConfigChange={noop}
      settingsRequest={0}
      renderAdvancedSettings={(tab) => <div>高级配置：{tab}</div>}
      onStartSession={noop}
      initialPanelState={initialPanelState}
    />,
  );
}

describe("HomePreviewWorkspace", () => {
  it("keeps the selected owned Avatar visible while its catalog is loading", () => {
    const html = renderHome("avatar", true, {
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      renderPath: "segmented",
      segmentedPresetId: "avatar-8657be31-306e-428d-a013-7521e710ab6a",
      segmentedAvatarId: "avatar-8657be31-306e-428d-a013-7521e710ab6a",
      segmentedDisplayName: "数字人1",
      segmentedAvatarActionId: "338a867c-0661-4565-af6e-f0f2e0e9b3c7",
    }, "collapsed");

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

  it("uses one shared workbench for Orb and digital-human configuration", () => {
    const html = renderHome("voice", true, DEFAULT_AVATAR_DISPLAY_CONFIG, "compact");

    expect(html).toContain("会话配置工作台");
    expect(html).toContain("视觉呈现");
    expect(html).not.toContain("SESSION STUDIO");
    expect(html).not.toContain("PRESENTATION");
    expect(html).not.toContain("轻触麦克风开始");
    expect(html).toContain('href="/avatars"');
    expect(html).toContain("数字人资产管理");
    expect(html).toContain('aria-label="收起会话配置工作台"');
    expect(html).toContain(">呈现</span>");
    expect(html).toContain(">音色</span>");
    expect(html).not.toContain("声音角色");
    expect(html).toContain('aria-label="主页呈现模式"');
    expect(html).toContain("对话</button>");
    expect(html).toContain("数字人</button>");
    expect(html).toContain('aria-label="主页开始对话"');
    expect(html).toContain('class="voice-start-halo"');
    expect(html).toContain('aria-label="视觉呈现模式"');
    expect(html).toContain("对话</button>");
    expect(html).toContain("数字人</button>");
    expect(html).not.toContain("Orb 对话");
    expect(html).not.toContain(">Orb 主题</span>");
    expect(html).toContain("液态玻璃");
    expect(html).toContain("调试面板");
    expect(html).not.toContain("浏览全部视觉主题");
    expect(html).toContain('data-theme="liquid-glass"');
    expect(html).toContain('data-theme="aurora-particles"');
    expect(html).toContain('data-theme="bars"');
    expect(html).not.toContain("选择 Orb 主题");
    expect(html).not.toContain("让声音成为界面本身");
    expect(html).toContain("使用对话模式开始对话");
    expect(html).toContain('aria-label="选择 Persona"');
    expect(html).toContain("未关联 Persona");
  });

  it("previews the selected runnable avatar before starting services", () => {
    const html = renderHome("avatar", true, undefined, "compact");

    expect(html).toContain("陪伴");
    expect(html).toContain("实时驱动");
    expect(html).toContain("多段式合成");
    expect(html).not.toMatch(/>0[12]<\/span>/);
    expect(html).toContain("Avatar 资产");
    expect(html).toContain("Avatar 资产（2）");
    expect(html).not.toContain("内置 Avatar");
    expect(html).toContain("口型模型");
    expect(html).not.toContain("本机口型模型");
    expect(html.indexOf("Avatar 资产")).toBeLessThan(html.indexOf("口型模型"));
    expect(html).toMatch(/<header><h3[^>]*>口型模型<\/h3><select[^>]*aria-label="口型模型选择"/);
    expect(html).toContain("Wav2Lip 256");
    const lipSyncModelOption = html.match(/<option[^>]*>[\s\S]*?<\/option>/)?.[0] ?? "";
    expect(lipSyncModelOption).toContain("Wav2Lip 256（默认）");
    expect(lipSyncModelOption).toContain('value="wav2lip256"');
    expect(lipSyncModelOption).toContain("selected");
    expect(lipSyncModelOption).not.toContain("disabled");
    expect(html).toContain('<option value="wav2lip96">Wav2Lip 96</option>');
    expect(html.indexOf("Wav2Lip 256（默认）")).toBeLessThan(html.indexOf("Wav2Lip 96"));
    expect(html).not.toContain("本机单会话长测 25 FPS");
    expect(html).not.toContain("DH_live_mini v1");
    expect(html).not.toContain("LiteAvatar");
    expect(html).not.toContain("FeatherTalk");
    expect(html).toContain("创建 Avatar 动作");
    expect(html).toContain('href="/avatars/create?task=action"');
    expect(html).not.toContain("创建数字人形象");
    expect(html).not.toContain("digital-human-workbench");
    expect(html).toContain('aria-label="多段式 Avatar 资产"');
    expect(html).toContain('aria-label="陪伴 形象与动作"');
    expect(html).not.toContain("选择只更新预览，开始对话后才启动服务");
    expect(html).not.toContain("首次使用会先准备口型资产，再自动开始对话");
    expect(html).not.toContain("傻妞 - DeepSeek V4 Flash");
    expect(html).not.toContain("语音服务就绪");
    expect(html).not.toContain("傻妞 · Realtime");
    expect(html).toContain("与 陪伴 对话");
    expect(html).toContain("与 陪伴 开始对话");
  });

  it("uses one Avatar card for its image and actions in segmented configuration", () => {
    const html = renderHome("avatar", true, undefined, "compact");

    expect(html).toContain('aria-label="多段式 Avatar 资产"');
    expect(html).toContain('aria-label="陪伴 形象与动作"');
    expect(html).not.toContain("数字人动作资产");
    expect(html).not.toContain("数字人形象资产");
    expect(html).not.toContain('aria-label="数字人动作资产列表"');
    expect(html).not.toContain('aria-label="数字人形象资产列表"');
  });

  it("shows only the two actual built-in Avatars before personal assets load", () => {
    const html = renderHome("avatar", true, undefined, "compact");

    expect(html).toContain('aria-label="Shuchang 形象与动作"');
    expect(html).toContain('aria-label="陪伴 形象与动作"');
    expect(html).not.toContain('aria-label="职场女 形象与动作"');
    expect(html.match(/aria-label="[^\"]+ 形象与动作"/g)).toHaveLength(2);
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

  it("separates realtime providers into personal and official avatar catalogs", () => {
    const html = renderHome("avatar", true, DEFAULT_AVATAR_DISPLAY_CONFIG, "compact");

    expect(html).toContain("实时驱动供应商");
    expect(html).not.toContain("REALTIME PROVIDER");
    expect(html).toContain('href="/avatars/create"');
    expect(html).toContain("创建数字人");
    expect(html).toContain("Anam");
    expect(html).toContain("HeyGen");
    expect(html).toContain("自定义");
    expect(html).toContain("自定义数字人");
    expect(html).toContain("官方数字人");
    expect(html).not.toContain("创建数字人形象");
    expect(html).not.toContain("digital-human-workbench");
    expect(html).toContain('aria-label="同步 Anam 数字人名称"');
    expect(html).toContain('aria-label="Anam 自定义数字人列表"');
    expect(html).toContain('aria-label="选择自定义数字人：当前配置形象"');
    expect(html).toContain('aria-label="展开官方数字人"');
    expect(html).not.toContain('aria-label="Anam 官方数字人列表"');
  });

  it("keeps the start action disabled until the voice connection is ready", () => {
    const html = renderHome("voice", false);

    expect(html).toContain("语音服务准备中");
    expect(html).toMatch(/<button[^>]*aria-label="主页开始对话"[^>]*disabled=""/);
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>.*语音服务准备中/s);
  });

  it("starts with a compact configuration launcher", () => {
    const html = renderHome("voice");

    expect(html).toContain('data-state="collapsed"');
    expect(html).toContain('aria-label="展开会话配置工作台"');
  });
});

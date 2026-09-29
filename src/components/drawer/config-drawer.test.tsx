import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import {
  BAILIAN_CLONED_VOICE_OPTIONS,
  BAILIAN_TTS_VOICE_OPTIONS,
  DEFAULT_TTS_VOICE,
  TTS_PROVIDER_OPTIONS,
  TTS_VOICE_OPTIONS,
  type TtsVoice,
} from "./voice-options";
import { MODEL_PROTOCOL_OPTIONS, MODEL_PROVIDER_OPTIONS } from "./model-options";
import { AvatarAssetDeleteDialog, ConfigDrawer, type ConfigTab } from "./config-drawer";
import {
  DEFAULT_AVATAR_DISPLAY_CONFIG,
  parseAvatarDisplayConfig,
  parseExperienceMode,
  type AvatarDisplayConfig,
  type ExperienceMode,
} from "@/components/digital-human/types";
import { VoiceClonePanel } from "./voice-clone-panel";

function renderDrawer(
  mode: ExperienceMode,
  avatarDisplayConfig: AvatarDisplayConfig = DEFAULT_AVATAR_DISPLAY_CONFIG,
  avatarConfigLocked = false,
  avatarArtifactPreviewEnabled = true,
  open = true,
  variant: "drawer" | "embedded" | "session" = "drawer",
  initialTab: ConfigTab = "display",
  sessionId: string | null = null,
  roleTts?: { provider: "bailian" | "doubao"; voice: TtsVoice },
) {
  return renderToStaticMarkup(
    <ConfigDrawer
      open={open}
      onClose={() => {}}
      setBargeInMuted={() => {}}
      setNoiseSuppression={() => {}}
      setVolume={() => {}}
      sessionId={sessionId}
      voiceVisualTheme="cloud"
      onVoiceVisualThemeChange={() => {}}
      ttsVoice={roleTts?.voice ?? DEFAULT_TTS_VOICE}
      initialTtsProvider={roleTts?.provider}
      useRoleTtsConfig={Boolean(roleTts)}
      ttsSpeechRate={0}
      ttsDialect=""
      ttsConfigurable
      ttsPreviewAvailable
      ttsConfigStatus=""
      onTtsVoiceChange={() => {}}
      onTtsSpeechRateChange={() => {}}
      onTtsDialectChange={() => {}}
      experienceMode={mode}
      onExperienceModeChange={() => {}}
      avatarDisplayConfig={avatarDisplayConfig}
      onAvatarDisplayConfigChange={() => {}}
      avatarConfigLocked={avatarConfigLocked}
      avatarArtifactPreviewEnabled={avatarArtifactPreviewEnabled}
      reducedMotion={false}
      onReducedMotionChange={() => {}}
      variant={variant}
      initialTab={initialTab}
    />,
  );
}

describe("ConfigDrawer", () => {
  it("initializes a role session with its selected speech provider", () => {
    const html = renderDrawer("avatar", DEFAULT_AVATAR_DISPLAY_CONFIG, true, true, true, "session", "voice", null,
      { provider: "bailian", voice: "longyingmu_v3" });

    expect(html).toContain("当前选择：阿里云百炼");
    expect(html).toContain("龙应沐 V3");
  });
  it("renders the pluggable experience modes and configuration tabs", () => {
    const html = renderDrawer("voice");

    expect(html).toContain("对话模式");
    expect(html).toContain("数字人模式");
    expect(html).not.toContain("聊天模式");
    expect(html).toContain('role="tablist"');
    expect(html.indexOf("呈现")).toBeLessThan(html.indexOf("模型"));
    expect(html.indexOf(">通用</button>")).toBeGreaterThan(html.indexOf(">对话</button>"));
    expect(html).toContain("呈现");
    expect(html).toContain("通用");
    expect(html).toContain("模型");
    expect(html).toContain("音色");
    expect(html).toContain("工具");
    expect(html).toContain("对话");
    expect(html).not.toContain(">外观</button>");
    expect(html).not.toContain("三种展示模式");
    expect(html).not.toContain("共用同一语音会话，只切换前端展示和播放载体");
    expect(html).not.toContain("正在配置：");
    expect(html).toContain('data-tooltip="视觉主题与实时声场"');
    expect(html).not.toContain("<span>说明</span>");
    expect(html).toContain("对话模式视觉");
    expect(html).not.toContain("<h4>数字人渲染</h4>");
  });

  it("uses the unified liquid workbench during an active session", () => {
    const html = renderDrawer(
      "avatar",
      DEFAULT_AVATAR_DISPLAY_CONFIG,
      true,
      true,
      true,
      "session",
      "display",
    );

    expect(html).toContain('data-variant="session"');
    expect(html).toContain('data-session-mode="avatar"');
    expect(html).toContain("会话配置工作台");
    expect(html).not.toContain("体验配置");
    expect(html).toContain("数字人 · 通话中");
    expect(html).toContain("当前会话呈现");
    expect(html).toContain("当前数字人呈现");
    expect(html).not.toContain('aria-label="设置展示模式"');
    expect(html).not.toContain('aria-label="体验预览"');
    expect(html).not.toContain("LIVE PREVIEW");
    expect(html).not.toContain("数字人形象资产库");
    expect(html).toContain('style="--panel-surface-alpha:0.30;--panel-highlight-alpha:0.072;--panel-soft-alpha:0.030;--panel-blur:3px"');
  });

  it("embeds an original configuration panel without mounting a second drawer shell", () => {
    const html = renderDrawer(
      "voice",
      DEFAULT_AVATAR_DISPLAY_CONFIG,
      false,
      true,
      true,
      "embedded",
      "model",
    );

    expect(html).toContain('data-variant="embedded"');
    expect(html).toContain('aria-label="高级会话配置"');
    expect(html).toContain("模型指令与角色配置");
    expect(html).toContain("模型供应商");
    expect(html).toContain('aria-label="模型供应商"');
    expect(html).toContain('data-tooltip="选择模型服务商后，会同步推荐模型、协议和接口默认值。"');
    expect(html).not.toContain('class="model-provider-grid"');
    expect(html).toContain('class="config-card config-card-disclosure"');
    expect(html).toContain("模型与接口定义");
    expect(html).toContain("系统提示词");
    expect(html).toMatch(/<h4>Persona<\/h4>/);
    expect(html).toContain('aria-label="选择 Persona"');
    expect(html).toContain("管理 Persona");
    expect(html).not.toContain("drawer-backdrop");
    expect(html).not.toContain("drawer-header");
    expect(html).not.toContain('role="dialog"');
    expect(html).not.toContain('role="tablist"');
  });

  it("keeps built-in tools visible and folds custom tool authoring", () => {
    const html = renderDrawer(
      "voice",
      DEFAULT_AVATAR_DISPLAY_CONFIG,
      false,
      true,
      true,
      "embedded",
      "tools",
    );

    expect(html).toContain("内置工具");
    expect(html).toContain("时间查询");
    expect(html).toContain("自定义工具");
    expect(html).toContain('class="config-card config-card-disclosure"');
    expect(html).not.toContain('class="config-card config-card-disclosure" open=""');
  });

  it("uses icon markers instead of numbered steps and folds conversation help into hints", () => {
    for (const tab of ["model", "voice", "tools", "conversation"] satisfies ConfigTab[]) {
      const html = renderDrawer("voice", DEFAULT_AVATAR_DISPLAY_CONFIG, false, true, true, "embedded", tab);
      expect(html).not.toMatch(/class="config-step">0[123]</);
    }

    const conversationHtml = renderDrawer("voice", DEFAULT_AVATAR_DISPLAY_CONFIG, false, true, true, "embedded", "conversation");
    expect(conversationHtml).not.toContain("<p>即时生效</p>");
    expect(conversationHtml).toContain('data-tooltip="打断与浏览器收音设置会立即应用到当前会话。"');
    expect(conversationHtml).toContain('data-tooltip="会话 ID 会在开始通话后生成。"');
  });

  it("renders the hosted asset configuration without provider administration", () => {
    const html = renderDrawer("avatar", { ...DEFAULT_AVATAR_DISPLAY_CONFIG, renderPath: "hosted", hostedAvatarDisplayName: "当前环境形象", hostedAvatarImageUrl: "/digital-human/shuchang-preview.jpg" });

    expect(html).toContain("当前环境形象 · CONFIG PREVIEW");
    expect(html).not.toContain("你好，我是 Shuchang");
    expect(html).toContain("%2Fdigital-human%2Fshuchang-preview.jpg");
    expect(html).toContain("数字人资产配置");
    expect(html).toContain("数字人形象资产库");
    expect(html).not.toContain("创建数字人形象");
    expect(html).not.toContain("数字人工作台 · 形象创建");
    expect(html).not.toContain("digital-human-workbench");
    expect(html).toContain("实时托管");
    expect(html).toContain("分段式合成");
    expect(html).toContain("选择已保存");
    expect(html).not.toContain("数字人图片生成提示词");
    expect(html).not.toContain("上传图片");
    expect(html).not.toContain("拍摄图片");
    expect(html).not.toContain("同步 Anam");
    expect(html).not.toContain("商业 API 成本");
    expect(html).not.toContain("Renderer 服务");
    expect(html).not.toContain("显示布局");
  });

  it("offers domestic, international, and custom model interfaces", () => {
    expect(MODEL_PROVIDER_OPTIONS.filter((provider) => provider.region === "国内").length).toBeGreaterThanOrEqual(6);
    expect(MODEL_PROVIDER_OPTIONS.filter((provider) => provider.region === "海外").length).toBeGreaterThanOrEqual(3);
    expect(MODEL_PROVIDER_OPTIONS.some((provider) => provider.value === "custom")).toBe(true);
    expect(MODEL_PROVIDER_OPTIONS.flatMap((provider) => provider.models).map((model) => model.value)).toContain("qwen3.8-max");
    expect(MODEL_PROTOCOL_OPTIONS.map((protocol) => protocol.value)).toContain("openai-chat-completions");
    expect(MODEL_PROTOCOL_OPTIONS.map((protocol) => protocol.value)).toContain("anthropic-messages");
  });

  it("renders the unified segmented Avatar library and workbench entry", () => {
    const html = renderDrawer("avatar", { ...DEFAULT_AVATAR_DISPLAY_CONFIG, renderPath: "segmented" });

    expect(html).toContain("Avatar 资产");
    expect(html).not.toContain("当前数字人形象");
    expect(html).not.toContain("动作所用数字人形象");
    expect(html).toContain("创建 Avatar 动作");
    expect(html).toContain("进入 Avatar 创建页 · 动作任务");
    expect(html).toContain('href="/avatars/create?task=action"');
    expect(html).toContain("Shuchang");
    expect(html).toContain("实时待机");
    expect(html).toContain("每个 Avatar 包含形象和所属动作");
    expect(html).toContain("左右浏览不会改变配置，点击后才更新");
    expect(html).not.toContain("口型模型");
    expect(html).not.toContain("DH_live_mini v1");
    expect(html).not.toContain("Provider credits");
    expect(html).not.toContain("/api/avatar-evaluation/artifacts/dh-live-mini-v1-custom-003");
    expect(html).toContain("MOTION SELECTED");
    expect(html).not.toContain("ACTION ASSET");
    expect(html).toContain("实时待机 · ACTION PREVIEW");
    expect(html).toContain('/digital-human/builtin-motion/shuchang-realtime-idle.mp4');
    expect(html).not.toContain("你好，我是 Shuchang");
    expect(html).toContain("分段式合成");
    expect(html).toContain("<small>Persona</small><strong>Shuchang</strong>");
    expect(html).toContain("<small>数字人动作</small><strong>实时待机</strong>");
    expect(html).not.toContain("<small>数字人形象</small>");
    expect(html).not.toContain("你好，我是 Shuchang 测试形象");
  });

  it("groups segmented images and actions into one card per Avatar", () => {
    const html = renderDrawer("avatar", { ...DEFAULT_AVATAR_DISPLAY_CONFIG, renderPath: "segmented" });

    expect(html).toContain("Avatar 资产");
    expect(html).toContain('aria-label="多段式 Avatar 资产"');
    expect(html).toContain('aria-label="陪伴 形象与动作"');
    expect(html).not.toContain("数字人动作资产库");
    expect(html).not.toContain("数字人形象资产库");
    expect(html).not.toContain('aria-label="数字人动作资产列表"');
    expect(html).not.toContain('aria-label="数字人形象资产列表"');
  });

  it("only exposes the two actual internal presets as canonical cards", () => {
    const html = renderDrawer("avatar", { ...DEFAULT_AVATAR_DISPLAY_CONFIG, renderPath: "segmented" });

    expect(html).toContain('aria-label="Shuchang 形象与动作"');
    expect(html).toContain('aria-label="陪伴 形象与动作"');
    expect(html).not.toContain('aria-label="职场女 形象与动作"');
    expect(html).not.toContain('aria-label="新闻主播 形象与动作"');
    expect(html).toContain("<strong>内置 Avatar</strong><span>2 个形象</span>");
  });

  it("keeps destructive asset actions out of the session workbench", () => {
    const html = renderDrawer("avatar", { ...DEFAULT_AVATAR_DISPLAY_CONFIG, renderPath: "segmented" });

    expect(html).not.toContain('aria-label="删除动作：');
    expect(html).not.toContain('aria-label="删除形象：');
  });

  it("explains the local deletion boundary before removing an asset", () => {
    const html = renderToStaticMarkup(
      <AvatarAssetDeleteDialog
        asset={{ kind: "motion", id: "opentalking:anchor", label: "主播 · 配套动作" }}
        onCancel={() => {}}
        onConfirm={() => {}}
      />,
    );

    expect(html).toContain('role="alertdialog"');
    expect(html).toContain("删除数字人动作？");
    expect(html).toContain("主播 · 配套动作");
    expect(html).toContain("只会从这台设备的资产库移除");
    expect(html).toContain("确认删除");
  });

  it("renders every selected built-in action as a playable right-side preview", () => {
    for (const motionId of ["avatar-bundled", "ffmpeg-static", "liveportrait-optimized"]) {
      const previewUrl = `/digital-human/builtin-motion/${motionId}.mp4`;
      const html = renderDrawer("avatar", {
        ...DEFAULT_AVATAR_DISPLAY_CONFIG,
        renderPath: "segmented",
        segmentedVideoId: motionId,
        segmentedAvatarActionId: `builtin:${motionId}`,
      });

      expect(html).toContain(`class="experience-preview-video" src="${previewUrl}"`);
      expect(html).toContain('autoPlay=""');
      expect(html).toContain(`播放动作预览：${motionId === "avatar-bundled" ? "内置循环动作" : motionId === "ffmpeg-static" ? "静态画面对照" : "自然交互动作"}`);
    }
  });

  it("keeps actions nested behind each Avatar image until the user browses", () => {
    const html = renderDrawer("avatar", { ...DEFAULT_AVATAR_DISPLAY_CONFIG, renderPath: "segmented" });

    expect(html).toContain('aria-label="展开 陪伴 的形象和动作"');
    expect(html).not.toContain('aria-label="浏览 陪伴 的下一个媒体"');
    expect(html).not.toContain('aria-label="预览动作：陪伴 · 内置动作"');
    expect(html).not.toContain('src="/digital-human/opentalking/companion/motion.mp4"');
  });

  it("does not split Avatar images into a second library", () => {
    const html = renderDrawer("avatar", { ...DEFAULT_AVATAR_DISPLAY_CONFIG, renderPath: "segmented" });

    expect(html).not.toContain("数字人形象资产库");
    expect(html).not.toContain('aria-label="数字人形象资产列表"');
    expect(html).not.toContain('class="avatar-identity-library-disclosure"');
  });

  it("previews a selected OpenTalking identity without presenting it as an action", () => {
    const html = renderDrawer("avatar", {
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      renderPath: "segmented",
      segmentedPresetId: "custom-upload",
      segmentedAvatarId: "newscaster",
      segmentedAvatarActionId: "",
    });

    expect(html).toContain("新闻主播 · 仅口型");
    expect(html).toContain("IDENTITY PREVIEW");
    expect(html).toContain("%2Fdigital-human%2Fopentalking%2Fnewscaster%2Fpreview.png");
    expect(html).toContain("<small>数字人形象</small><strong>新闻主播</strong>");
    expect(html).not.toContain("新闻主播 · ACTION PREVIEW");
  });

  it("mounts only the selected action preview, never evaluation or lip-sync comparison videos", () => {
    const html = renderDrawer(
      "avatar",
      {
        ...DEFAULT_AVATAR_DISPLAY_CONFIG,
        renderPath: "segmented",
        segmentedAvatarId: "companion",
        segmentedAvatarActionId: "builtin:opentalking:companion",
      },
      false,
      false,
    );

    expect(html).toContain("<video");
    expect(html).toContain("/digital-human/opentalking/companion/motion.mp4");
    expect(html).not.toContain("/api/avatar-evaluation/artifacts/");
  });

  it("unmounts the artifact video when the settings drawer closes", () => {
    const html = renderDrawer(
      "avatar",
      { ...DEFAULT_AVATAR_DISPLAY_CONFIG, renderPath: "segmented" },
      false,
      true,
      false,
    );

    expect(html).not.toContain("<video");
    expect(html).not.toContain("/api/avatar-evaluation/artifacts/");
  });

  it("unmounts packaged motion videos when the settings drawer closes", () => {
    const html = renderDrawer(
      "avatar",
      {
        ...DEFAULT_AVATAR_DISPLAY_CONFIG,
        renderPath: "segmented",
        segmentedAvatarId: "newscaster",
        segmentedAvatarActionId: "builtin:opentalking:newscaster",
      },
      false,
      true,
      false,
    );

    expect(html).not.toContain("<video");
    expect(html).toContain("新闻主播 · 配套动作");
  });

  it("keeps hidden lip-sync implementation choices out of asset configuration", () => {
    const html = renderDrawer("avatar", {
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      renderPath: "segmented",
      segmentedLipSyncId: "musetalk15",
    });

    expect(html).not.toContain("口型模型");
    expect(html).not.toContain("/api/avatar-evaluation/artifacts/musetalk");
  });

  it("does not expose model compatibility diagnostics in the asset selector", () => {
    const html = renderDrawer("avatar", {
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      renderPath: "segmented",
      segmentedPresetId: "liteavatar-preset",
      segmentedLipSyncId: "wav2lip256",
    });

    expect(html).not.toContain("CONFIG BLOCKED");
    expect(html).not.toContain("请选择人物预置底片");
    expect(html).not.toContain("<small>模式</small><strong>实时数字人</strong>");
  });

  it("narrows persisted avatar display configuration to supported values", () => {
    expect(parseAvatarDisplayConfig({
      provider: "unknown",
      surface: "offscreen",
      segmentedPresetId: "retired-avatar",
      segmentedVideoId: "missing-video",
      segmentedLipSyncId: "unknown-model",
      fallbackToClassic: false,
    })).toEqual(DEFAULT_AVATAR_DISPLAY_CONFIG);
    expect(parseAvatarDisplayConfig({ renderPath: "segmented", provider: "heygen", surface: "pip", framing: "full", ratio: "9:16", quality: "latency" })).toMatchObject({
      renderPath: "segmented",
      provider: "heygen",
      surface: "pip",
      framing: "full",
      ratio: "9:16",
      quality: "latency",
      fallbackToClassic: true,
    });
    expect(parseAvatarDisplayConfig({ segmentedPresetId: "liteavatar-preset", segmentedVideoId: "liveportrait-optimized" })).toMatchObject({
      segmentedPresetId: "liteavatar-preset",
      segmentedVideoId: "avatar-bundled",
      segmentedLipSyncId: "liteavatar",
    });
    expect(parseAvatarDisplayConfig({ segmentedPresetId: "shuchang", segmentedVideoId: "avatar-bundled" })).toMatchObject({
      segmentedPresetId: "shuchang",
      segmentedVideoId: "liveportrait-optimized",
    });
    expect(parseAvatarDisplayConfig({
      segmentedAvatarId: "custom-12345678-1234-4123-8123-123456789abc",
      segmentedAvatarActionId: "motion-base:accepted-001",
    })).toMatchObject({
      segmentedAvatarId: "custom-12345678-1234-4123-8123-123456789abc",
      segmentedAvatarActionId: "motion-base:accepted-001",
    });
    expect(parseAvatarDisplayConfig({ segmentedAvatarActionId: "<script>" }))
      .toMatchObject({ segmentedAvatarActionId: "builtin:shuchang-realtime-idle" });
  });

  it("keeps invalid legacy combinations out of the primary page messaging", () => {
    const html = renderDrawer("avatar", {
      ...DEFAULT_AVATAR_DISPLAY_CONFIG,
      renderPath: "segmented",
      segmentedPresetId: "shuchang",
      segmentedVideoId: "avatar-bundled",
      segmentedLipSyncId: "dh-live-mini-v1",
    });

    expect(html).not.toContain("CONFIG BLOCKED");
    expect(html).not.toContain("当前人物没有预置底片");
    expect(html).not.toContain("组合可进入本地评测");
  });

  it("migrates the legacy classic display mode to voice", () => {
    expect(parseExperienceMode("classic")).toBe("voice");
    expect(parseExperienceMode("chat")).toBe("voice");
    expect(parseExperienceMode("avatar")).toBe("avatar");
  });

  it("locks display mode and renderer controls after a voice session starts", () => {
    const html = renderDrawer("avatar", DEFAULT_AVATAR_DISPLAY_CONFIG, true);

    expect(html).toContain("当前展示模式已绑定到本次会话，结束后可重新选择");
    expect(html).toMatch(/<button[^>]*role="radio"[^>]*aria-checked="false"[^>]*disabled=""/);
    expect(html).toMatch(/<div class="avatar-render-mode-grid"[^>]*>[\s\S]*?<button[^>]*disabled=""/);
    expect(html).not.toContain("显示布局");
  });

  it("keeps provider voice catalogs and cloned voices separate", () => {
    expect(TTS_PROVIDER_OPTIONS.map((provider) => provider.value)).toEqual(["bailian", "doubao"]);
    expect(BAILIAN_TTS_VOICE_OPTIONS.length).toBeGreaterThan(0);
    expect(TTS_VOICE_OPTIONS.length).toBeGreaterThan(BAILIAN_TTS_VOICE_OPTIONS.length);
    expect(BAILIAN_CLONED_VOICE_OPTIONS[0].description).toContain("默认克隆音色");

    const html = renderDrawer(
      "voice",
      DEFAULT_AVATAR_DISPLAY_CONFIG,
      false,
      true,
      true,
      "embedded",
      "voice",
    );
    expect(html.indexOf("<h4>语音供应商</h4>")).toBeLessThan(html.indexOf("<h4>内置音色</h4>"));
    expect(html.indexOf("<h4>内置音色</h4>")).toBeLessThan(html.indexOf("<h4>克隆音色</h4>"));
    expect(html).toContain('aria-label="语音供应商选择"');
    expect(html).toContain("当前选择：火山引擎");
    expect(html).not.toContain('class="provider-choice-grid"');
    expect(html).not.toContain("当前选择已保存为草稿");
    expect(html).not.toContain("Session Profile");
    expect(html).not.toContain("运行中：");
    expect(html).toContain("添加音色");
    expect(html).toContain('class="config-card voice-library-disclosure"');

    const bailianCloneHtml = renderToStaticMarkup(
      <VoiceClonePanel
        provider="bailian"
        selectedVoice={BAILIAN_CLONED_VOICE_OPTIONS[0].value}
        previewVoice={null}
        previewState="idle"
        onSelect={() => {}}
        onPreview={() => {}}
      />,
    );
    expect(bailianCloneHtml).toContain('aria-label="克隆音色列表"');
    expect(bailianCloneHtml.indexOf('class="voice-clone-toolbar"')).toBeLessThan(bailianCloneHtml.indexOf('aria-label="克隆音色列表"'));
    expect(bailianCloneHtml).toContain("0 个可用音色");

    const embeddedCloneHtml = renderToStaticMarkup(
      <VoiceClonePanel embedded provider="bailian" selectedVoice="" previewVoice={null} previewState="idle" onSelect={() => {}} onPreview={() => {}} />,
    );
    expect(embeddedCloneHtml).toContain("新建克隆");
    expect(embeddedCloneHtml).toContain('data-embedded="true"');
  });

  it("keeps the workbench general and conversation controls concise", () => {
    const generalHtml = renderDrawer("voice", DEFAULT_AVATAR_DISPLAY_CONFIG, false, true, true, "embedded", "general");
    expect(generalHtml).not.toContain("深色主题");
    expect(generalHtml).toContain("减少预览动态");

    const conversationHtml = renderDrawer("voice", DEFAULT_AVATAR_DISPLAY_CONFIG, false, true, true, "embedded", "conversation", "session-123");
    expect(conversationHtml).toContain('aria-label="复制会话 ID"');
    expect(conversationHtml).not.toContain(">复制</button>");
  });
});

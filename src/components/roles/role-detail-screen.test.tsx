import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const component = readFileSync(new URL("./role-detail-screen.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("./role-detail-screen.module.css", import.meta.url), "utf8");
const voiceSelector = readFileSync(new URL("../voice/voice-selector.tsx", import.meta.url), "utf8");

describe("role detail configuration workspace", () => {
  it("opens a draggable liquid-glass configuration window from the top-right button", () => {
    expect(component).toContain('aria-label="打开角色配置"');
    expect(component).toContain("onPointerDown={startConfigDrag}");
    expect(component).toContain("onPointerMove={moveConfigPanel}");
    expect(component).not.toContain("homeControlsStyles.rightHandle");
    expect(component).not.toContain("mobileConfigButton");
    expect(css).toMatch(/\.configPanel\s*\{[^}]*backdrop-filter:\s*blur\(var\(--role-glass-blur\)\)/s);
  });

  it("uses an inspector-width default and supports pointer resizing on desktop", () => {
    expect(component).toContain("useState(480)");
    expect(component).toContain("onPointerDown={startConfigResize}");
    expect(component).toContain("onPointerMove={resizeConfigPanel}");
    expect(component).toContain('aria-label="调整配置窗口宽度"');
    expect(component).toContain('"--config-width": `${configWidth}px`');
    expect(css).toContain("width: min(var(--config-width),calc(100vw - var(--workspace-sidebar-width,52px) - 36px))");
  });

  it("matches role creation with progressive top-level modules and nested base settings", () => {
    expect(component).toContain('type ConfigSection = "foundation" | "presentation" | "avatar" | "realtime" | "action" | "talking" | null');
    expect(component).toContain('type ConfigModule = "voice" | "persona" | "tools" | "knowledge" | null');
    expect(component).not.toContain('<nav className={styles.configNav}');
    expect(component).not.toContain('aria-label="角色信息设置"');
    expect(component).toContain('<ConfigTaskModule id="foundation"');
    expect(component).toContain('<ConfigTaskModule id="presentation"');
    expect(component).toContain('<ConfigTaskModule id="avatar"');
    expect(component).toContain('<ConfigTaskModule id="action"');
    expect(component).toContain('<ConfigTaskModule id="talking"');
    expect(component).toContain('aria-label="声音设置"');
    expect(component).toContain('aria-label="Persona 设置"');
    expect(component).toContain('aria-label="工具使用设置"');
    expect(component).toContain('aria-label="知识库设置"');
    expect(component).toContain("<VoiceSelector");
    expect(voiceSelector).toContain('/api/tts/preview?');
    expect(component).not.toContain('fetch("/api/conversations"');
  });

  it("opens the shared digital-human production window inside role settings", () => {
    expect(component).toContain("<AvatarProductionOverlay");
    expect(component).toContain('openProductionTask("motion")');
    expect(component).toContain('openProductionTask("talking")');
    expect(component).toContain('aria-label="新建动作"');
    expect(component).toContain('className={styles.actionCardGrid}');
  });

  it("creates a realtime avatar from the current role image instead of managing a catalog image", () => {
    expect(component).toContain("创建数字人形象");
    expect(component).toContain("sourceAvatar={avatar}");
    expect(component).toContain("sourceName={role.display_name}");
    expect(component).toContain("finishRealtimeCreation(hostedAvatar)");
    expect(component).toContain("saveHostedAvatarProfile(hostedAvatar.id");
    expect(component).toContain("memoryEnabled: role.memory_enabled, documentIds: knowledgeIds, toolIds: role.tool_ids");
    expect(component).not.toContain("选择实时数字人</span><select");
  });

  it("keeps unavailable realtime and lip-sync modes out of the role detail presentation", () => {
    expect(component).toContain("roleDetailDisplayMode(activeMode, lipSyncReady");
    expect(component).toContain('showRealtimeOption={false}');
    expect(component).toContain("mode={displayMode}");
    expect(component).toContain("ROLE_MODE_LABELS[displayMode]");
    expect(component).not.toContain("styles.realtimeShortcut");
  });

  it("reuses the creation-flow avatar cards in role settings", () => {
    expect(component).toContain('<AvatarChoiceGrid avatars={avatars} value={role.avatar_id} onChange={selectAvatar} onManage={assetManagement.manage} busy={assetManagement.busy} />');
    expect(component).not.toContain("styles.avatarPicker");
  });

  it("uses the role name as the panel title with inline editing", () => {
    expect(component).toContain('<strong>{role.display_name}</strong>');
    expect(component).toContain('editingRoleName ? "完成角色名称编辑" : "编辑角色名称"');
    expect(component).toContain('className={styles.roleNameInput}');
    expect(component).not.toContain('<h2>角色配置</h2>');
  });

  it("organizes voices by provider, clone, official and dialect lists", () => {
    expect(component).toContain("<VoiceSelector");
    expect(voiceSelector).toContain('aria-label="声音供应商"');
    expect(voiceSelector).toContain('title="音色克隆"');
    expect(voiceSelector).toContain('aria-label="官方音色"');
    expect(voiceSelector).toContain('aria-label="方言"');
    expect(voiceSelector).toContain('<VoiceClonePanel embedded');
    expect(component).toContain('voiceDialect: role.voice_dialect ?? ""');
    expect(component).toContain('voice_dialect: voice.dialect');
    expect(voiceSelector).not.toContain('className={styles.providerGroup}');
    expect(voiceSelector).toContain('item.scope === "personal" ? "个人配置" : "平台配置"');
  });

  it("keeps selection and production inside the role editor", () => {
    const component = readFileSync(new URL("./role-detail-screen.tsx", import.meta.url), "utf8");

    expect(component).toContain("onManage={assetManagement.manage}");
    expect(component).toContain("<DeletedAssets");
    expect(component).not.toContain("管理当前形象与动作");
    expect(component).toContain('openProductionTask("avatar")');
    expect(component).toContain("allowClone allowManagement={false}");
  });

  it("auto-saves valid role changes and removes the explicit save action", () => {
    expect(component).toContain("const autoSaveTimerRef");
    expect(component).toContain("所有更改自动保存");
    expect(component).not.toContain("保存修改");
  });

  it("resolves the initial action from the current default presentation mode", () => {
    expect(component).toContain('selectedRole.default_mode === "offline"');
    expect(component).toContain('selectedRole.default_selections?.[selectedRole.default_mode]?.action_id');
    expect(component).not.toContain("returnedActionId ?? selectedRole.default_selections?.offline?.action_id ??");
  });

  it("does not expose action video as a presentation mode", () => {
    expect(component).toContain('ROLE_PRESENTATION_MODES.filter((mode) => mode !== "motion" &&');
  });

  it("lets users select an unavailable mode and presents its missing setup as a task", () => {
    expect(component).not.toContain("if (!role || !presentationModeAvailable(mode)) return");
    expect(component).not.toContain("disabled={!available ||");
    expect(component).toContain('available ? "当前形象素材可用" : "选择后继续完成所需配置"');
    expect(component).toContain('<ConfigTaskModule id="realtime"');
    expect(component).toContain("const configurationReady =");
    expect(component).toContain("disabled={saving || !configurationReady}");
  });

  it("preserves pending mode choices while a resource setup page is open", () => {
    expect(component).toContain("enabledModes: role?.enabled_modes");
    expect(component).toContain("defaultMode: role?.default_mode");
    expect(component).toContain("snapshot.enabledModes");
  });

  it("preserves pending local modes but invalidates the previous realtime identity when changing avatars", () => {
    expect(component).toContain('role.enabled_modes.filter((mode) => mode !== "realtime")');
    expect(component).toContain("enabled_modes: enabledModes");
    expect(component).toContain("if (identityChanged) setSelectedRealtimeAvatarId(null)");
    expect(component).toContain("!identityChanged && role.default_selections?.realtime");
  });

  it("reuses the homepage mode and material controls without the homepage role rail", () => {
    expect(component).toContain("<HomeRoleModeControls");
    expect(component).toContain("showRoleSelector={false}");
    expect(component).toContain("onModeSelect={selectPresentationPreview}");
    expect(component).not.toContain("homeControlsStyles.modePanel");
    expect(component).not.toContain("homeControlsStyles.bottomHandle");
  });

  it("presents capabilities as labeled lists without exposing model id", () => {
    expect(component).toContain("工具使用");
    expect(component).toContain("知识库");
    expect(component).toContain("长期记忆");
    expect(component).toContain('tool.builtin ? "内置" : tool.public_enabled ? "共享" : "个人"');
    expect(component).not.toContain("模型 ID（高级配置）");
  });
});

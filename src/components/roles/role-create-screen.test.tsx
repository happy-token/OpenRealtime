import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const component = readFileSync(new URL("./role-create-screen.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("./role-create-screen.module.css", import.meta.url), "utf8");

describe("role creation progressive flow", () => {
  it("separates multi-select presentation modes from common role settings", () => {
    expect(component).toContain('id="foundation"');
    expect(component).toContain('id="modes"');
    expect(component).toContain('title="呈现模式"');
    expect(component).toContain("draft.modes.includes(mode)");
    expect(component).toContain('const needsRealtime = draft.modes.includes("realtime")');
    expect(component).toContain('const needsAction = draft.modes.includes("offline") || draft.modes.includes("lip-sync")');
    expect(component).toContain('const needsTalking = draft.modes.includes("offline")');
    expect(css).toMatch(/\.modeList\s*\{[^}]*display:grid/s);
  });

  it("removes the review accordion and keeps one persistent create action", () => {
    expect(component).not.toContain('id="review"');
    expect(component).not.toContain('title="创建确认"');
    expect(component).toContain('className={styles.createFooter}');
    expect(component).toContain("incompleteSteps.map");
    expect(component).toContain("handleCreateAction");
    expect(css).toMatch(/\.createFooter\s*\{[^}]*grid-template-columns:minmax\(0,1fr\) auto/s);
  });

  it("uses the shared voice selector with clone, preview and dialect persistence", () => {
    expect(component).toContain("<VoiceSelector");
    expect(component).toContain("allowClone allowManagement");
    expect(component).toContain("voiceDialect: draft.voiceDialect");
    expect(component).toContain("onSelectionCommit={() => setOpenBaseSetting(null)}");
  });

  it("auto-collapses single-choice assets while leaving explicit completion for multi-select settings", () => {
    expect(component).toContain("setOpenModule(null); }");
    expect(component).toContain("setOpenBaseSetting(null)");
    expect(component).toContain(">完成选择</button>");
    expect(component).toContain("onOpen(open ? null : id)");
  });

  it("uses the shared avatar cards so creation and role settings stay visually aligned", () => {
    expect(component).toContain("<AvatarChoiceGrid");
    expect(component).toContain("onChange={selectAvatar}");
    expect(css).not.toContain(".avatarGrid");
  });

  it("opens personal talking-material creation with the selected action and Lip Forcing method", () => {
    expect(component).toContain('`/services/talking?avatar_id=${encodeURIComponent(avatar.avatar_id)}&action_id=${encodeURIComponent(action.avatar_action_id)}&return_to=role-create&method=lipforcing`');
  });
});

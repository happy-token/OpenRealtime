import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const component = readFileSync(new URL("./role-list-screen.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("./role-list-screen.module.css", import.meta.url), "utf8");

describe("role list cards", () => {
  it("keeps card actions compact without a mode-label row", () => {
    expect(component).toContain("aria-label={t(\"删除角色\") + (t(role.display_name)) + \"\"}");
    expect(component).toContain('<Trash2 />');
    expect(component).toContain('!isProtectedBuiltinRole(role.role_id) && !isDefault');
    expect(component).not.toContain('className={styles.capabilities}');
    expect(css).toMatch(/\.cardActions\s*\{[^}]*bottom:\s*18px/s);
  });

  it("requires confirmation before deleting a role", () => {
    expect(component).toContain('role="alertdialog"');
    expect(component).toContain('await deleteRole(pendingDeleteRole.role_id)');
    expect(component).toContain("数字人形象、人设和声音资源不会被删除");
  });

  it("uses client navigation for role details", () => {
    expect(component).toContain('<Link className={styles.detailButton}');
    expect(component).not.toContain('<a className={styles.detailButton}');
  });

  it("creates a draft role and opens role settings without a separate creation page", () => {
    expect(component).toContain("await createRole({");
    expect(component).toContain("displayName: \"未命名角色\"");
    expect(component).toContain("selectedDefaultTtsProvider");
    expect(component).toContain('voiceProvider === "bailian" ? BAILIAN_TTS_VOICE_OPTIONS[0].value : DEFAULT_TTS_VOICE');
    expect(component).toContain("router.push(`/roles/${encodeURIComponent(created.role_id)}?settings=1`)");
    expect(component).not.toContain('href="/roles/new"');
  });

  it("shows the complete role portrait without cropping or stretching it", () => {
    expect(css).toMatch(/\.portrait img\s*\{[^}]*object-fit:\s*contain[^}]*object-position:\s*center/s);
  });

  it("keeps the new-role label visible on narrow screens", () => {
    expect(component).toContain("新建角色");
    expect(css).not.toMatch(/\.createButton\s*\{[^}]*font-size:\s*0\s*;/s);
    expect(css).toContain(".createButton { width: 100%; justify-content: center; }");
  });
});

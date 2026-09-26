import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const component = readFileSync(new URL("./role-list-screen.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("./role-list-screen.module.css", import.meta.url), "utf8");

describe("role list cards", () => {
  it("places an icon-only delete action beside the mode list", () => {
    expect(component).toContain('aria-label={`删除角色${role.display_name}`}');
    expect(component).toContain('<Trash2 />');
    expect(component).toContain('role.role_id !== "default-assistant" && !isDefault');
    expect(css).toMatch(/\.capabilities\s*\{[^}]*justify-content:\s*space-between/s);
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
    expect(component).toContain('displayName: "未命名角色"');
    expect(component).toContain("router.push(`/roles/${encodeURIComponent(created.role_id)}`)");
    expect(component).not.toContain('href="/roles/new"');
  });

  it("shows the complete role portrait without cropping or stretching it", () => {
    expect(css).toMatch(/\.portrait img\s*\{[^}]*object-fit:\s*contain[^}]*object-position:\s*center/s);
  });
});

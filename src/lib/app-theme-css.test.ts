import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

function read(relativeUrl: string) {
  return readFileSync(new URL(relativeUrl, import.meta.url), "utf8");
}

describe("global theme CSS coverage", () => {
  it("defines shared semantic control and accent tokens", () => {
    const tokens = read("../styles/tokens.css");

    expect(tokens).toContain("--control-surface:");
    expect(tokens).toContain("--accent-surface:");
    expect(tokens).toContain("--accent-contrast:");
    expect(tokens).toContain("--accent-shadow:");
  });

  it("keeps avatar primary actions connected to the active theme", () => {
    const shell = read("../components/avatar/avatar-page-shell.module.css");

    expect(shell).toMatch(/--avatar-primary-bg:[^;]*var\(--accent\)/);
    expect(shell).toMatch(/--avatar-primary-border:[^;]*var\(--accent\)/);
    expect(shell).not.toContain("rgba(124,111,255");
  });

  it("does not let page shells replace the global accent", () => {
    const workspace = read("../components/call/preview-workspace-lab.module.css");
    const admin = read("../app/admin/admin.module.css");

    expect(workspace).not.toMatch(/--accent:\s*#/);
    expect(admin).toContain("--admin-accent: var(--accent)");
  });
});

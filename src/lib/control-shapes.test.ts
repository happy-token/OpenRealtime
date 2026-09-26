import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const globals = readFileSync(new URL("../styles/globals.css", import.meta.url), "utf8");
const tokens = readFileSync(new URL("../styles/tokens.css", import.meta.url), "utf8");

describe("shared control shapes", () => {
  it("gives buttons and native selects shared rounded defaults", () => {
    expect(tokens).toContain("--button-radius: 12px");
    expect(tokens).toContain("--dropdown-radius: 13px");
    expect(globals).toMatch(/button\s*\{\s*border-radius:\s*var\(--button-radius\)/);
    expect(globals).toMatch(/body select:not\(\[multiple\]\)\s*\{\s*border-radius:\s*var\(--dropdown-radius\)/);
  });

  it("keeps custom dropdown panels rounded and themed", () => {
    expect(globals).toMatch(/\.select-menu-popover\s*\{[^}]*border-radius:\s*var\(--dropdown-popover-radius\)/s);
    expect(globals).toMatch(/\.select-menu-popover\s*\{[^}]*border:\s*1px solid var\(--border-strong\)/s);
  });
});

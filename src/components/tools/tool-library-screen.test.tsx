import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const component = readFileSync(new URL("./tool-library-screen.tsx", import.meta.url), "utf8");

describe("ToolLibraryScreen actions", () => {
  it("names the icon-only edit action while keeping state controls textual", () => {
    expect(component).toContain('aria-label={`编辑工具${tool.display_name}`}');
    expect(component).toContain('<Pencil />');
    expect(component).not.toContain('onClick={() => edit(tool)}>编辑</button>');
    expect(component).toContain('"公开可用" : "仅内部"');
    expect(component).toContain('"已启用" : "已停用"');
  });
});

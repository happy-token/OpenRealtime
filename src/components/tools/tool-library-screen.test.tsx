import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const component = readFileSync(new URL("./tool-library-screen.tsx", import.meta.url), "utf8");

describe("ToolLibraryScreen actions", () => {
  it("names the icon-only edit action while keeping state controls textual", () => {
    expect(component).toContain("aria-label={t(\"编辑工具\") + (tool.display_name) + \"\"}");
    expect(component).toContain('<Pencil />');
    expect(component).not.toContain('onClick={() => edit(tool)}>编辑</button>');
    expect(component).toContain("t(\"公开可用\") : t(\"仅内部\")");
    expect(component).toContain("t(\"已启用\") : t(\"已停用\")");
  });
});

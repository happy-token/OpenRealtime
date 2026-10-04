import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ToolPermissionsScreen } from "./tool-permissions-screen";

describe("tool permissions screen", () => {
  it("explains all permission modes without showing an unsaved default as active", () => {
    const html = renderToStaticMarkup(<ToolPermissionsScreen />);
    expect(html).toContain("全局权限模式");
    expect(html).not.toContain('type="radio"');
    expect(html).toContain("继承全局");
    expect(html).toContain("正在读取权限设置");
    expect(html).not.toContain('checked=""');
  });
});

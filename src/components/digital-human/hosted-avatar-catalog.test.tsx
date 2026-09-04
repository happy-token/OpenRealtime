import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { HostedAvatarCatalog } from "./hosted-avatar-catalog";

describe("HostedAvatarCatalog", () => {
  it("only exposes selectable hosted assets without the unfinished appearance creator", () => {
    const html = renderToStaticMarkup(
      <HostedAvatarCatalog
        active={false}
        disabled={false}
        selectedAvatarId="default-anam"
        onSelect={() => {}}
      />,
    );

    expect(html).not.toContain("创建数字人形象");
    expect(html).not.toContain("数字人工作台 · 形象创建");
    expect(html).not.toContain('href="/digital-human-workbench?tool=appearance"');
    expect(html).toContain("我的形象");
    expect(html).toContain("内置形象");
    expect(html).toContain("当前环境形象");
    expect(html).toContain('aria-label="搜索数字人形象"');
    expect(html).not.toContain("Provider Connection");
    expect(html).not.toContain("同步 Anam");
    expect(html).not.toContain("商业 API 成本");
    expect(html).not.toContain("创建 Anam Hosted Avatar");
    expect(html).not.toContain("待创建形象");
  });
});

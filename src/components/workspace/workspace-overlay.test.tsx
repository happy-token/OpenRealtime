import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { WorkspaceOverlay } from "./workspace-overlay";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ back: vi.fn() }),
  usePathname: () => "/roles",
}));

describe("WorkspaceOverlay", () => {
  it("renders route content as adjustable liquid glass above the retained home page", () => {
    const html = renderToStaticMarkup(<WorkspaceOverlay label="角色"><h1>角色</h1></WorkspaceOverlay>);

    expect(html).toContain('data-workspace-overlay="true"');
    expect(html).toContain('data-home-backdrop="true"');
    expect(html).toContain('data-page-glass="true"');
    expect(html).toContain('aria-label="角色"');
    expect(html).toContain('aria-label="关闭页面"');
    expect(html).toContain("<h1>角色</h1>");
  });
});

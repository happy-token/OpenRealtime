import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import Loading from "@/app/loading";

vi.mock("next/navigation", () => ({
  usePathname: () => "/docs",
  useRouter: () => ({ push: vi.fn() }),
}));

describe("route loading state", () => {
  it("announces navigation progress while the next route is prepared", () => {
    const html = renderToStaticMarkup(<Loading />);

    expect(html).toContain('role="status"');
    expect(html).toContain('aria-label="正在切换页面"');
    expect(html).toContain('id="workspace-navigation"');
  });
});

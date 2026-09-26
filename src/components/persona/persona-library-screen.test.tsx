import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

import { PersonaLibraryScreen } from "./persona-library-screen";

describe("PersonaLibraryScreen", () => {
  it("renders the intro and the create-Persona card while the list is loading", () => {
    const html = renderToStaticMarkup(<PersonaLibraryScreen />);
    expect(html).toContain("<h2>人设</h2>");
    expect(html).toContain("正在加载 Persona 列表");
    expect(html).toContain("创建人设");
    expect(html).not.toContain("正在为");
  });

  it("shows a linking banner naming the Avatar when linkingAvatarId is set", () => {
    const html = renderToStaticMarkup(<PersonaLibraryScreen linkingAvatarId="avatar-zhaoning" linkingAvatarDisplayName="昭宁" />);
    expect(html).toContain("正在为");
    expect(html).toContain("昭宁");
  });

  it("falls back to the raw Avatar id in the banner when no display name is given", () => {
    const html = renderToStaticMarkup(<PersonaLibraryScreen linkingAvatarId="avatar-zhaoning" />);
    expect(html).toContain("avatar-zhaoning");
  });
});

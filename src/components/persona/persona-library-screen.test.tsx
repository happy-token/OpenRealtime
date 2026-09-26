import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

import { PersonaLibraryScreen } from "./persona-library-screen";

describe("PersonaLibraryScreen", () => {
  it("places the create button beside the heading while the list is loading", () => {
    const html = renderToStaticMarkup(<PersonaLibraryScreen />);
    expect(html).toContain("<h2>人设</h2>");
    expect(html).toContain("正在加载 Persona 列表");
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain("创建人设");
    expect(html).not.toContain('data-create="true"');
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

  it("keeps renaming in the editor and hides the technical Persona ID from creation", () => {
    const source = readFileSync(new URL("./persona-library-screen.tsx", import.meta.url), "utf8");
    expect(source).toContain('aria-label={`${persona.personaName}的人设名称`}');
    expect(source).not.toContain('aria-label="Persona ID"');
    expect(source).not.toContain('>更名</button>');
    expect(source).not.toContain("createId");
  });

  it("gives icon-only edit and create-panel close actions accessible names", () => {
    const source = readFileSync(new URL("./persona-library-screen.tsx", import.meta.url), "utf8");
    expect(source).toContain('aria-label={`编辑人设${persona.personaName}`}');
    expect(source).toContain('aria-label="关闭创建人设"');
    expect(source).not.toContain('<Pencil />编辑</button>');
    expect(source).not.toContain('>关闭</button>');
  });
});

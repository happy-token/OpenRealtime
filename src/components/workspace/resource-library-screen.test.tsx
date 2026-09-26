import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { canDeleteClonedVoice, canRepairMissingCloneSelection } from "@/components/drawer/voice-clone-panel";
import { BAILIAN_CLONED_VOICE_OPTIONS } from "@/components/drawer/voice-options";
import { ProviderKeyGate } from "@/components/provider-key/provider-key-gate";
import { ResourceLibraryScreen } from "./resource-library-screen";
import { VoiceLibrary } from "./voice-library";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("@/hooks/use-official-realtime-avatars", () => ({
  useOfficialRealtimeAvatars: () => ({
    avatars: [{ id: "official-one", origin: "official", displayName: "官方形象", imageUrl: "" }],
    personalAvatars: [{ id: "personal-one", origin: "personal", displayName: "我的形象", imageUrl: "" }],
    configured: true,
    loading: false,
  }),
}));

describe("ResourceLibraryScreen", () => {
  it("omits the redundant resource-library introduction on category pages", () => {
    const html = renderToStaticMarkup(<ResourceLibraryScreen tab="voices" />);
    expect(html).toContain("声音");
    expect(html).not.toContain("可复用内容");
    expect(html).not.toContain("统一管理可供角色复用");
  });

  it("allows provider clones to be deleted while protecting the built-in placeholder", () => {
    expect(canDeleteClonedVoice("voice-active", true)).toBe(true);
    expect(canDeleteClonedVoice(BAILIAN_CLONED_VOICE_OPTIONS[0].value, true)).toBe(false);
    expect(canDeleteClonedVoice("voice-other", true)).toBe(true);
    expect(canDeleteClonedVoice("voice-other", false)).toBe(false);
  });

  it("does not repair a clone selection while the provider catalog is unavailable", () => {
    expect(canRepairMissingCloneSelection(true, false)).toBe(false);
    expect(canRepairMissingCloneSelection(false, true)).toBe(false);
    expect(canRepairMissingCloneSelection(true, true)).toBe(true);
  });

  it("uses four expandable modules and shares the role clone workflow", () => {
    const html = renderToStaticMarkup(<VoiceLibrary />);
    const css = readFileSync(new URL("./resource-library-screen.module.css", import.meta.url), "utf8");
    const librarySource = readFileSync(new URL("./voice-library.tsx", import.meta.url), "utf8");
    const selectorSource = readFileSync(new URL("../voice/voice-selector.tsx", import.meta.url), "utf8");
    const selectorCss = readFileSync(new URL("../voice/voice-selector.module.css", import.meta.url), "utf8");
    const roleSource = readFileSync(new URL("../roles/role-detail-screen.tsx", import.meta.url), "utf8");

    expect(html).toContain("供应商选择");
    expect(html).toContain("音色克隆");
    expect(html).toContain("官方音色");
    expect(html).toContain("方言支持");
    expect(html).toContain("新建克隆音色");
    expect(html.match(/aria-expanded="false"/g)).toHaveLength(4);
    expect(librarySource).toContain("<VoiceSelector");
    expect(selectorSource).toContain("<VoiceClonePanel");
    expect(roleSource).toContain("<VoiceSelector");
    expect(selectorSource).toContain('aria-label="官方音色"');
    expect(selectorSource).toContain("toggleVoicePreview");
    expect(selectorCss).toMatch(/\.moduleList\s*\{[^}]*display:\s*grid/s);
    expect(selectorCss).toMatch(/\.choiceList\s*\{[^}]*max-height:\s*320px[^}]*overflow-y:\s*auto/s);
    expect(css).toMatch(/\.sharedVoiceSelector\s*\{[^}]*width:\s*min\(840px,100%\)/s);
  });

  it("keeps avatar, action, and talking assets in one digital-human surface", () => {
    const html = renderToStaticMarkup(<ProviderKeyGate><ResourceLibraryScreen tab="avatars" returnToRoleId="role-personal-123" /></ProviderKeyGate>);

    expect(html).toContain('aria-label="数字人资产主页"');
    expect(html).toContain("创建形象");
    expect(html).not.toContain("配置实时驱动");
    expect(html).toContain("生成动作");
    expect(html).toContain("新建口型动作");
    expect(html).not.toContain("/services/motion");
    expect(html).not.toContain("/services/talking");
  });

  it("does not expose motion as a separate resource category", () => {
    const source = readFileSync(new URL("./resource-library-screen.tsx", import.meta.url), "utf8");

    expect(source).not.toContain('{ id: "motion"');
    expect(source).not.toContain('tab === "motion"');
  });

  it("shows personal real-time avatars first and keeps official avatars collapsed", () => {
    const html = renderToStaticMarkup(<ResourceLibraryScreen tab="official-realtime" />);
    expect(html.indexOf("我的数字人形象")).toBeLessThan(html.indexOf("官方配置的数字人形象"));
    expect(html).toContain('<details class="');
    expect(html).not.toContain("<details open");
    expect(html).toContain("创建数字人");
    expect(html).toContain("/resources?tab=official-realtime&amp;task=realtime");
    expect(html).toContain("/resources/realtime/personal-one");
    expect(html).toContain("/resources/realtime/official-one");
  });
});

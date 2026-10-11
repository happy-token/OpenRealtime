import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { translate } from "@/components/language/language-provider";
import { DocumentIndex, DocumentReader } from "./document-pages";
import { VoiceStartButton } from "@/components/ui/voice-start-button";

vi.mock("@/components/language/language-provider", async importOriginal => {
  const actual = await importOriginal<typeof import("@/components/language/language-provider")>();
  return { ...actual, useLanguage: () => ({ language: "en", t: (text: string, params?: Record<string, string>) => actual.translate(text, "en", params) }) };
});

describe("English documentation UI", () => {
  it("renders English directory titles, categories and descriptions", () => {
    const html = renderToStaticMarkup(<DocumentIndex />);
    expect(html).toContain("Documentation reader");
    expect(html).toContain(translate("模块化话轮协调器", "en"));
    expect(html).not.toMatch(/[\u3400-\u9fff]/);
  });
  it("keeps document prose unchanged while translating reader navigation", () => {
    const html = renderToStaticMarkup(<DocumentReader slug="quick-start" title="首页使用指南" content="暂不翻译的正文" />);
    expect(html).toContain(translate("首页使用指南", "en"));
    expect(html).toContain("暂不翻译的正文");
    expect(html).toContain('lang="zh-CN"');
    expect(html).not.toContain("文档目录");
  });
  it("localizes default call controls and their connection hints", () => {
    for (const connected of [true, false]) {
      const html = renderToStaticMarkup(<VoiceStartButton connected={connected} onPress={() => undefined} />);
      expect(html).not.toMatch(/[\u3400-\u9fff]/);
    }
  });
});

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
  it("leads with voice experience and Agent integration, keeping tutorials and research secondary", () => {
    const html = renderToStaticMarkup(<DocumentIndex />);
    expect(html).toContain('href="/conversation?role_mode=conversation&amp;experience=voice"');
    expect(html).toContain("Try real-time voice");
    expect(html).toContain("Smart turn detection. Room to think.");
    expect(html).toContain("Smart interruptions. Intent matters.");
    expect(html.indexOf('href="/docs/chat-agent-integration"')).toBeLessThan(html.indexOf('href="/docs/product-assistant"'));
    expect(html).not.toContain("Prepare product docs");
    expect(html).not.toContain("Configure a Q&amp;A role");
    expect(html).not.toContain("Test voice Q&amp;A");
    expect(html).toMatch(/<details[^>]*><summary>Research and planning<\/summary>/);
    expect(html).toContain("Optional: add an avatar");
  });
  it("uses the authored English article and resolves links relative to that source", () => {
    const html = renderToStaticMarkup(<DocumentReader slug="product-assistant" title="产品助手" content="中文配置流程" englishContent={"## Start here\n\n[Overview](OVERVIEW.en.md)"} />);
    expect(html).toContain('lang="en"');
    expect(html).toContain('href="/docs/overview"');
    expect(html).toContain('id="start-here"');
    expect(html).not.toContain("中文配置流程");
  });
  it("preserves usable Chinese fragment anchors when no English body exists", () => {
    const html = renderToStaticMarkup(<DocumentReader slug="quick-start" title="首页使用指南" content={"## 开始语音对话\n\n[帮助](getting-started/PRODUCT-ASSISTANT.md#开始前)\n\n## 开始语音对话"} />);
    expect(html).toContain('id="开始语音对话"');
    expect(html).toContain('id="开始语音对话-1"');
    expect(html).toContain('href="/docs/product-assistant#%E5%BC%80%E5%A7%8B%E5%89%8D"');
  });
  it("localizes default call controls and their connection hints", () => {
    for (const connected of [true, false]) {
      const html = renderToStaticMarkup(<VoiceStartButton connected={connected} onPress={() => undefined} />);
      expect(html).not.toMatch(/[\u3400-\u9fff]/);
    }
  });
});

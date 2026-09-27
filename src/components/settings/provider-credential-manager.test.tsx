import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ProviderCredentialManager } from "./provider-credential-manager";

describe("ProviderCredentialManager capability layout", () => {
  it("separates ASR, TTS and LLM without presenting a shared voice test as ASR verification", () => {
    const html = renderToStaticMarkup(<ProviderCredentialManager />);
    expect(html).toContain("ASR · 语音识别");
    expect(html).not.toContain("Bella ASR");
    expect(html).toContain("TTS · 语音合成");
    expect(html).toContain("LLM · 对话模型");
    expect(html).toContain("ASR 能力测试将在 bridge 契约接入后开放");
    expect(html.indexOf("ASR · 语音识别")).toBeLessThan(html.indexOf("TTS · 语音合成"));
    expect(html.indexOf("TTS · 语音合成")).toBeLessThan(html.indexOf("LLM · 对话模型"));
  });

  it("shows only auxiliary services in advanced settings", () => {
    const html = renderToStaticMarkup(<ProviderCredentialManager mode="other" />);
    expect(html).toContain("Anam");
    expect(html).toContain("MiniMax");
    expect(html).not.toContain("豆包 ASR");
    expect(html).not.toContain("旧版供应商 Key");
  });
});

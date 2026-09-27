import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import { ProviderInstanceManager } from "./provider-instance-manager";
import { PROVIDER_SCOPE_DISPLAY_ORDER } from "./provider-scope-order";

it("offers only the supported built-in provider catalog and a consistent create flow", () => {
  const html = renderToStaticMarkup(<ProviderInstanceManager admin={false} />);
  expect(html).toContain("ASR · 语音识别");
  expect(html).toContain("TTS · 语音合成");
  expect(html).toContain("LLM · 对话模型");
  expect(html).toContain("新建供应商");
  expect(html).not.toContain("Bella ASR");
  expect(html).toContain("自定义 bridge 在隔离运行环境就绪前不会执行用户代码");
  expect(PROVIDER_SCOPE_DISPLAY_ORDER).toEqual(["platform", "personal"]);
});

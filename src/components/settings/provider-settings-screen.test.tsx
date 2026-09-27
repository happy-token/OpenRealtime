import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ProviderSettingsScreen } from "./provider-settings-screen";

describe("ProviderSettingsScreen", () => {
  it("keeps supplier instances separate from model and legacy services", () => {
    const html = renderToStaticMarkup(<ProviderSettingsScreen />);
    expect(html).toContain("新建供应商");
    expect(html).toContain("高级服务");
    expect(html).toContain("Anam");
    expect(html).toContain("MiniMax");
    expect(html).toContain("实时数字人");
    expect(html).toContain("视频生成");
    expect(html).not.toContain('id="model-services"');
    expect(html).not.toContain("旧版供应商 Key 与其他服务");
  });

  it("does not embed model services for an administrator", () => {
    const html = renderToStaticMarkup(<ProviderSettingsScreen showPlatformModelServices />);
    expect(html).not.toContain("模型服务配置");
  });
});

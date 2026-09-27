import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import { AdvancedServiceManager } from "./advanced-service-manager";

it("groups advanced suppliers by capability and offers the shared creation flow", () => {
  const html = renderToStaticMarkup(<AdvancedServiceManager />);
  expect(html).toContain("实时数字人");
  expect(html).toContain("视频生成");
  expect(html).toContain("新建供应商");
  expect(html).toContain("我的配置");
  expect(html).toContain("平台配置");
  expect(html.indexOf("平台配置")).toBeLessThan(html.indexOf("我的配置"));
  expect(html).not.toContain("Bella");
});

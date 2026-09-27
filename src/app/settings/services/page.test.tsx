import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/headers", () => ({ cookies: async () => ({ get: () => undefined }) }));
vi.mock("@/components/workspace/workspace-shell", () => ({ WorkspaceShell: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
vi.mock("@/components/settings/model-services-settings", () => ({ ModelServicesSettings: ({ scope }: { scope: string }) => <div>{scope}模型服务配置</div> }));

import ServicesPage from "./page";

describe("model services page", () => {
  it("renders a standalone personal service page", async () => {
    const html = renderToStaticMarkup(await ServicesPage());
    expect(html).toContain("模型服务");
    expect(html).toContain("personal模型服务配置");
    expect(html).not.toContain("platform模型服务配置");
  });
});

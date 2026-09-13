import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { AvatarCapabilityNotice } from "./avatar-capability-notice";

describe("AvatarCapabilityNotice", () => {
  it("keeps the initial capability check visually quiet", () => {
    const html = renderToStaticMarkup(
      <AvatarCapabilityNotice capability={undefined} error={null} onRetry={vi.fn()} />,
    );

    expect(html).toBe("");
    expect(html).not.toContain("正在检查数字人");
  });

  it("keeps actionable capability results visible", () => {
    const html = renderToStaticMarkup(
      <AvatarCapabilityNotice
        capability={{ state: "not_configured", message: "此环境尚未启用数字人。" }}
        error={null}
        onRetry={vi.fn()}
      />,
    );

    expect(html).toContain("此环境尚未启用数字人。");
    expect(html).toContain("role=\"status\"");
  });

  it("shows retry when the check fails", () => {
    const html = renderToStaticMarkup(
      <AvatarCapabilityNotice capability={undefined} error="能力检查超时，请重试。" onRetry={vi.fn()} />,
    );

    expect(html).toContain("能力检查超时，请重试。");
    expect(html).toContain("重新检查");
  });
});

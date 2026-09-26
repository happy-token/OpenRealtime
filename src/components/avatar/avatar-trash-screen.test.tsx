import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { AvatarTrashScreen } from "./avatar-trash-screen";

describe("AvatarTrashScreen", () => {
  it("keeps the empty state concise and fully localized", () => {
    const html = renderToStaticMarkup(<AvatarTrashScreen />);

    expect(html).toContain("回收站");
    expect(html).toContain("删除内容保留 30 天，期间可恢复。");
    expect(html).toContain("回收站是空的");
    expect(html).not.toContain("Avatar / Recycle Bin");
    expect(html).not.toContain("删除的资产会在这里保留 30 天");
  });

  it("returns an empty role-scoped trash view to its originating role", () => {
    const html = renderToStaticMarkup(<AvatarTrashScreen returnHref="/roles/role-personal-123" />);

    expect(html).toContain('href="/roles/role-personal-123"');
  });
});

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { mergeAccessibleAvatarRecords, ProductionServiceScreen, productionServiceHref } from "./production-service-screen";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

describe("ProductionServiceScreen", () => {
  it("keeps a role return target while switching production services", () => {
    const html = renderToStaticMarkup(<ProductionServiceScreen kind="motion" returnToRoleId="role-personal-123" />);

    expect(html).toContain('href="/roles/role-personal-123"');
    expect(html).toContain('href="/services/motion?return_to=role-personal-123"');
    expect(html).toContain('href="/services/talking?return_to=role-personal-123"');
  });

  it("returns to role creation and keeps that context between services", () => {
    const html = renderToStaticMarkup(<ProductionServiceScreen kind="talking" returnToRoleCreate />);

    expect(html).toContain('href="/roles/new"');
    expect(html).toContain("返回创建角色");
    expect(html).toContain('href="/services/motion?return_to=role-create"');
    expect(html).toContain('href="/services/talking?return_to=role-create"');
  });

  it("returns standalone production work to the merged digital-human library", () => {
    const html = renderToStaticMarkup(<ProductionServiceScreen kind="motion" />);

    expect(html).toContain('href="/resources?tab=avatars"');
    expect(html).toContain("返回数字人");
  });

  it("preserves the selected avatar and action while moving between production tools", () => {
    expect(productionServiceHref("/services/motion", "avatar-personal-123", "action-idle", "role-personal-123"))
      .toBe("/services/motion?avatar_id=avatar-personal-123&return_to=role-personal-123");
    expect(productionServiceHref("/services/talking", "avatar-personal-123", "action-idle", "role-personal-123"))
      .toBe("/services/talking?avatar_id=avatar-personal-123&action_id=action-idle&return_to=role-personal-123");
  });

  it("preserves the requested Lip Forcing method from role creation", () => {
    expect(productionServiceHref(
      "/services/talking",
      "avatar-personal-123",
      "action-idle",
      "role-create",
      "lipforcing",
    )).toBe("/services/talking?avatar_id=avatar-personal-123&action_id=action-idle&return_to=role-create&method=lipforcing");
  });

  it("preserves role creation context when the empty workbench creates a digital human", () => {
    expect(productionServiceHref("/avatars/create", undefined, undefined, "role-create"))
      .toBe("/avatars/create?return_to=role-create");
  });

  it("keeps personal avatars available when the administrator catalog is unavailable", () => {
    const personal = { avatar_id: "avatar-personal-123", deleted_at: null } as never;
    expect(mergeAccessibleAvatarRecords([
      { status: "rejected", reason: new Error("forbidden") },
      { status: "fulfilled", value: [personal] },
    ])).toEqual({ accessible: true, avatars: [personal] });
  });
});

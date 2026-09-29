import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const component = readFileSync(new URL("./role-action-composer.tsx", import.meta.url), "utf8");
const page = readFileSync(new URL("../../app/roles/new/action/page.tsx", import.meta.url), "utf8");

describe("role action composer return flow", () => {
  it("opens new actions without restoring the last server generation", () => {
    expect(component).toContain("freshCreation");
  });
  it("returns newly created actions to an existing role editor when requested", () => {
    expect(page).toContain("return_to?: string");
    expect(page).toContain("avatarResourceHref({");
    expect(page).toContain("returnTo: isRoleRecordId(query.return_to) ? query.return_to : undefined");
    expect(component).toContain("returnTo?: string");
    expect(component).toContain("router.replace(`/roles/${encodeURIComponent(returnTo)}`)");
    expect(component).toContain('"新动作已创建并选中"');
    expect(component).toContain("returnTo ? t(\"角色设置\") : t(\"角色创建任务\")");
  });
});

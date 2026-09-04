import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { PersonaQuickSelect } from "./persona-quick-select";

describe("PersonaQuickSelect", () => {
  it("renders nothing when there is no avatar to link a Persona to", () => {
    const html = renderToStaticMarkup(<PersonaQuickSelect avatarId={null} avatarDisplayName="" />);
    expect(html).toBe("");
  });

  it("renders a compact Persona picker defaulting to unlinked before data loads", () => {
    const html = renderToStaticMarkup(<PersonaQuickSelect avatarId="default-anam" avatarDisplayName="Shuchang" />);
    expect(html).toContain('aria-label="选择 Persona"');
    expect(html).toContain("未关联 Persona");
  });
});

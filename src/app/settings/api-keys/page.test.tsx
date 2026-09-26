import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ redirect: (path: string) => { throw new Error(`redirect:${path}`); } }));

import LegacyApiKeySettingsPage from "./page";

describe("legacy API Key settings route", () => {
  it("opens the unified supplier settings page", () => {
    expect(() => LegacyApiKeySettingsPage()).toThrow("redirect:/settings/providers");
  });
});

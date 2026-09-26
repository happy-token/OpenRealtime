import { describe, expect, it } from "vitest";
import { isRouteNavigation, shouldShowRouteLoading } from "./navigation-events";

describe("navigation feedback", () => {
  const current = new URL("http://localhost/settings?tab=account#profile");

  it("shows for same-origin route and query changes", () => {
    expect(isRouteNavigation(new URL("http://localhost/roles"), current)).toBe(true);
    expect(isRouteNavigation(new URL("http://localhost/settings?tab=appearance"), current)).toBe(true);
  });

  it("ignores external, same-URL, and hash-only links", () => {
    expect(isRouteNavigation(new URL("https://example.com/settings"), current)).toBe(false);
    expect(isRouteNavigation(new URL(current.href), current)).toBe(false);
    expect(isRouteNavigation(new URL("http://localhost/settings?tab=account#security"), current)).toBe(false);
  });

  it("keeps settings subpage changes free of the full-screen loading overlay", () => {
    expect(shouldShowRouteLoading(new URL("http://localhost/settings/appearance"), current)).toBe(false);
    expect(shouldShowRouteLoading(new URL("http://localhost/settings/providers"), new URL("http://localhost/settings/appearance"))).toBe(false);
    expect(shouldShowRouteLoading(new URL("http://localhost/conversation"), current)).toBe(true);
  });
});

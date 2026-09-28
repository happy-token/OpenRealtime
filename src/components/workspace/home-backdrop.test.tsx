import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { HomeBackdrop } from "./home-backdrop";

const navigation = vi.hoisted(() => ({ pathname: "/resources" }));
vi.mock("next/navigation", () => ({ usePathname: () => navigation.pathname }));
vi.mock("@/components/call/orb", () => ({ Orb: () => <div data-orb="true" /> }));

describe("HomeBackdrop", () => {
  it.each(["/resources", "/resources/personas", "/services/motion", "/services/talking"])(
    "does not render the old home avatar in resource editor %s", (pathname) => {
      navigation.pathname = pathname;
      const html = renderToStaticMarkup(<HomeBackdrop />);
      expect(html).toContain('data-mode="neutral"');
      expect(html).not.toContain("background-image");
      expect(html).not.toContain("shuchang");
      expect(html).not.toContain("data-orb");
    },
  );

  it("uses a neutral fallback on other workspace pages", () => {
    navigation.pathname = "/roles";
    const html = renderToStaticMarkup(<HomeBackdrop />);
    expect(html).toContain('data-mode="neutral"');
    expect(html).not.toContain("shuchang-preview.jpg");
  });
});

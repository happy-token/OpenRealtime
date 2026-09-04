import { describe, expect, it } from "vitest";
import nextConfig, { resolveNextDistDir } from "../../next.config";

describe("Next.js build output isolation", () => {
  it("keeps development output separate from production output", () => {
    expect(resolveNextDistDir("development")).toBe(".next-dev");
    expect(resolveNextDistDir("production")).toBe(".next");
    expect(resolveNextDistDir("test")).toBe(".next");
    expect(nextConfig.distDir).toBe(".next");
  });

  it("allows an isolated output directory for a concurrent E2E server", () => {
    expect(resolveNextDistDir("development", ".next-e2e-3000")).toBe(".next-e2e-3000");
  });
});

import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

describe("development web launcher", () => {
  it("uses Turbopack so cold route navigation does not wait on Webpack compilation", () => {
    const launcher = readFileSync(path.join(process.cwd(), "scripts", "dev_web.sh"), "utf8");

    expect(launcher).toContain("next dev --turbopack");
  });
});

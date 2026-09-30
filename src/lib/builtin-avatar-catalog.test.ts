import { access } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";
import catalog from "@/data/builtin-avatar-catalog.json";
import { INTERNAL_AVATAR_PRESET_IDS } from "./internal-avatar-ids";

describe("packaged built-in avatars", () => {
  it("contains three curated identities and all referenced local media", async () => {
    expect(catalog.map((avatar) => avatar.avatar_id)).toEqual([...INTERNAL_AVATAR_PRESET_IDS]);
    const urls = new Set<string>();
    for (const avatar of catalog) {
      expect(avatar.actions.length).toBeGreaterThan(0);
      for (const action of avatar.actions) {
        urls.add(action.video_url);
        for (const variant of action.talking_variants) urls.add(variant.video_url);
      }
    }
    for (const name of ["samantha", "qingzhao", "ruoshui"]) {
      urls.add(`/digital-human/builtin-avatars/${name}.webp`);
    }
    for (const url of urls) {
      expect(url).toMatch(/^\/digital-human\/[a-z0-9/.-]+$/);
      await access(path.join(process.cwd(), "public", url));
    }
  });
});

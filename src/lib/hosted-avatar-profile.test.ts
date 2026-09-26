import { afterEach, describe, expect, it, vi } from "vitest";
import { defaultHostedAvatarProfile, readHostedAvatarProfile, saveHostedAvatarProfile } from "./hosted-avatar-profile";

afterEach(() => vi.unstubAllGlobals());

describe("hosted avatar profile", () => {
  it("starts with a basic conversation profile", () => {
    expect(defaultHostedAvatarProfile("官方形象")).toMatchObject({ displayName: "官方形象", personaId: null, toolIds: [] });
  });

  it("saves settings separately for each avatar", () => {
    const values = new Map<string, string>();
    vi.stubGlobal("window", { localStorage: { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => values.set(key, value) } });
    saveHostedAvatarProfile("official-a", { ...defaultHostedAvatarProfile("A"), personaId: "persona-1", toolIds: ["tool-1"] });
    expect(readHostedAvatarProfile("official-a", "A")).toMatchObject({ personaId: "persona-1", toolIds: ["tool-1"] });
    expect(readHostedAvatarProfile("official-b", "B")).toMatchObject({ displayName: "B", personaId: null, toolIds: [] });
  });
});

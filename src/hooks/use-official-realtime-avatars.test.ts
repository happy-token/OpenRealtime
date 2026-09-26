import { describe, expect, it } from "vitest";
import type { AnamHostedAvatar } from "@/lib/anam-avatars";
import { officialRealtimeAvatarsFromCatalog, personalRealtimeAvatarsFromCatalog } from "./use-official-realtime-avatars";

describe("officialRealtimeAvatarsFromCatalog", () => {
  const official = { id: "official-one", origin: "official" } as AnamHostedAvatar;
  const personal = { id: "personal-one", origin: "personal" } as AnamHostedAvatar;

  it("shows only official cards from a configured catalog", () => {
    expect(officialRealtimeAvatarsFromCatalog({ configured: true, avatars: [official, personal] })).toEqual([official]);
  });

  it("hides the catalog when Anam is not configured", () => {
    expect(officialRealtimeAvatarsFromCatalog({ configured: false, avatars: [official] })).toEqual([]);
    expect(officialRealtimeAvatarsFromCatalog(null)).toEqual([]);
  });

  it("shows custom real-time avatars only when the provider is configured", () => {
    expect(personalRealtimeAvatarsFromCatalog({ configured: true, avatars: [official, personal] })).toEqual([personal]);
    expect(personalRealtimeAvatarsFromCatalog({ configured: false, avatars: [personal] })).toEqual([]);
  });
});

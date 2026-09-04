import { afterEach, describe, expect, it, vi } from "vitest";
import {
  AVATAR_IDENTITY_DISPLAY_NAMES_STORAGE_KEY,
  CUSTOM_AVATAR_IDENTITY_STORAGE_KEY,
  deleteStoredCustomAvatarIdentity,
  readStoredAvatarIdentityDisplayName,
  readStoredCustomAvatarIdentity,
  readStoredCustomAvatarIdentities,
  renameStoredCustomAvatarIdentity,
  storeAvatarIdentityDisplayName,
} from "./avatar-identity-sync";

afterEach(() => vi.unstubAllGlobals());

describe("custom avatar identity persistence", () => {
  it("migrates a legacy custom-upload record to a stable identity instance", () => {
    const values = new Map<string, string>();
    values.set(CUSTOM_AVATAR_IDENTITY_STORAGE_KEY, JSON.stringify({
      name: "person.jpg",
      dataUrl: "data:image/jpeg;base64,/9j/",
      updatedAt: "2026-08-25T00:00:00.000Z",
    }));
    const localStorage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
    };
    vi.stubGlobal("window", { localStorage });

    const first = readStoredCustomAvatarIdentity();
    const second = readStoredCustomAvatarIdentity();
    expect(first?.identityId).toMatch(/^custom-[0-9a-f-]{36}$/);
    expect(second?.identityId).toBe(first?.identityId);
    expect(first?.sourceSha256).toBe("legacy-unverified");
  });

  it("preserves multiple uploaded identities while keeping one explicit selection", () => {
    const values = new Map<string, string>();
    values.set(CUSTOM_AVATAR_IDENTITY_STORAGE_KEY, JSON.stringify({
      version: 2,
      selectedIdentityId: "custom-22222222-2222-4222-8222-222222222222",
      identities: [
        {
          identityId: "custom-11111111-1111-4111-8111-111111111111",
          name: "one.jpg",
          dataUrl: "data:image/jpeg;base64,/9j/",
          sourceSha256: "one",
          updatedAt: "2026-08-24T00:00:00.000Z",
        },
        {
          identityId: "custom-22222222-2222-4222-8222-222222222222",
          name: "two.jpg",
          dataUrl: "data:image/jpeg;base64,/9j/",
          sourceSha256: "two",
          updatedAt: "2026-08-25T00:00:00.000Z",
        },
      ],
    }));
    vi.stubGlobal("window", {
      localStorage: {
        getItem: (key: string) => values.get(key) ?? null,
        setItem: (key: string, value: string) => values.set(key, value),
      },
    });

    expect(readStoredCustomAvatarIdentities()).toHaveLength(2);
    expect(readStoredCustomAvatarIdentity()?.name).toBe("two.jpg");
  });

  it("stores editable display names by stable identity id and suggests a suffix for duplicates", () => {
    const values = new Map<string, string>();
    vi.stubGlobal("window", {
      localStorage: {
        getItem: (key: string) => values.get(key) ?? null,
        setItem: (key: string, value: string) => values.set(key, value),
      },
      dispatchEvent: vi.fn(),
    });

    expect(storeAvatarIdentityDisplayName("shuchang", "小舒")).toBe("小舒");
    expect(storeAvatarIdentityDisplayName("custom-11111111-1111-4111-8111-111111111111", "小舒")).toBe("小舒 2");
    expect(readStoredAvatarIdentityDisplayName("shuchang", "Shuchang 测试形象")).toBe("小舒");
    expect(JSON.parse(values.get(AVATAR_IDENTITY_DISPLAY_NAMES_STORAGE_KEY) ?? "{}")).toMatchObject({ shuchang: "小舒" });
  });

  it("renames and deletes an uploaded identity while repairing the explicit selection", () => {
    const values = new Map<string, string>();
    values.set(CUSTOM_AVATAR_IDENTITY_STORAGE_KEY, JSON.stringify({
      version: 2,
      selectedIdentityId: "custom-22222222-2222-4222-8222-222222222222",
      identities: [
        { identityId: "custom-11111111-1111-4111-8111-111111111111", name: "one.jpg", dataUrl: "data:image/jpeg;base64,/9j/", sourceSha256: "one", updatedAt: "2026-08-24T00:00:00.000Z" },
        { identityId: "custom-22222222-2222-4222-8222-222222222222", name: "two.jpg", dataUrl: "data:image/jpeg;base64,/9j/", sourceSha256: "two", updatedAt: "2026-08-25T00:00:00.000Z" },
      ],
    }));
    vi.stubGlobal("window", {
      localStorage: { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => values.set(key, value) },
      dispatchEvent: vi.fn(),
    });
    vi.stubGlobal("CustomEvent", class { constructor(public type: string) {} });

    expect(renameStoredCustomAvatarIdentity("custom-22222222-2222-4222-8222-222222222222", "品牌主持人")?.name).toBe("品牌主持人");
    expect(deleteStoredCustomAvatarIdentity("custom-22222222-2222-4222-8222-222222222222")).toBe(true);
    expect(readStoredCustomAvatarIdentities().map((identity) => identity.name)).toEqual(["one.jpg"]);
    expect(readStoredCustomAvatarIdentity()?.identityId).toBe("custom-11111111-1111-4111-8111-111111111111");
  });
});

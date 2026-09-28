import { afterEach, describe, expect, it, vi } from "vitest";
import { orderRoleActions, readAvatarActionOrder, readRoleActionPreferences, rememberAvatarActionOrder, rememberRoleActionOrder, rememberRoleActionSelection } from "./role-action-preferences";

afterEach(() => vi.unstubAllGlobals());

function useMemoryStorage() {
  const values = new Map<string, string>();
  vi.stubGlobal("window", { dispatchEvent: vi.fn(), localStorage: {
    get length() { return values.size; },
    key: (index: number) => [...values.keys()][index] ?? null,
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value); },
  } });
}

describe("role action preferences", () => {
  it("shares action order per avatar while keeping each role's selected variants separate", () => {
    useMemoryStorage();
    rememberRoleActionOrder("role-a", "avatar-a", ["second", "first"]);
    rememberRoleActionSelection("role-a", "avatar-a", "first", "variant-one");
    rememberRoleActionSelection("role-a", "avatar-a", "second", "variant-two");

    expect(readRoleActionPreferences("role-a", "avatar-a")).toEqual({
      order: ["second", "first"], actionId: "second", variantId: "variant-two",
      variants: { first: "variant-one", second: "variant-two" },
    });
    expect(readRoleActionPreferences("role-b", "avatar-a").order).toEqual(["second", "first"]);
    expect(readRoleActionPreferences("role-b", "avatar-a").variants).toEqual({});
    rememberAvatarActionOrder("avatar-a", ["first", "second"]);
    expect(readRoleActionPreferences("role-a", "avatar-a").order).toEqual(["first", "second"]);
    expect(readRoleActionPreferences("role-a", "avatar-a").variantId).toBe("variant-two");
    expect(readRoleActionPreferences("role-a", "avatar-b").actionId).toBeUndefined();
  });

  it("uses a previously saved role order on the homepage until a shared order is saved", () => {
    useMemoryStorage();
    window.localStorage.setItem("openrealtime:role-action-preferences:role-a:avatar-a", JSON.stringify({ order: ["second", "first"] }));
    expect(readAvatarActionOrder("avatar-a")).toEqual(["second", "first"]);
    rememberAvatarActionOrder("avatar-a", ["first", "second"]);
    expect(readAvatarActionOrder("avatar-a")).toEqual(["first", "second"]);
    expect(readAvatarActionOrder("avatar-b")).toEqual([]);
  });

  it("places new actions after saved ones without changing their source order", () => {
    expect(orderRoleActions(["first", "second", "third", "fourth"], ["third", "first", "removed"], (id) => id))
      .toEqual(["third", "first", "second", "fourth"]);
  });
});

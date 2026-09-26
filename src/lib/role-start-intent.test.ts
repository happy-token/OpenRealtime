import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { consumeRoleStartIntent, saveRoleStartIntent } from "./role-start-intent";

const data = new Map<string, string>();

beforeEach(() => {
  data.clear();
  vi.stubGlobal("window", { sessionStorage: {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => { data.set(key, value); },
    removeItem: (key: string) => { data.delete(key); },
  } });
  vi.spyOn(Date, "now").mockReturnValue(1_000_000);
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("role start intent", () => {
  it("consumes the user's recent click only for the selected role", () => {
    saveRoleStartIntent("role-a");
    expect(consumeRoleStartIntent("role-a")).toBe(true);
    expect(consumeRoleStartIntent("role-a")).toBe(false);
  });

  it("does not start another role or replay an old click", () => {
    saveRoleStartIntent("role-a");
    expect(consumeRoleStartIntent("role-b")).toBe(false);
    saveRoleStartIntent("role-a");
    vi.spyOn(Date, "now").mockReturnValue(1_031_000);
    expect(consumeRoleStartIntent("role-a")).toBe(false);
  });
});

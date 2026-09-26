import { afterEach, describe, expect, it, vi } from "vitest";
import { completeRoleCreationResource, ROLE_CREATE_DRAFT_KEY } from "./role-creation-workbench-context";

describe("role creation resource handoff", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("selects the newly created action and clears an incompatible talking material", () => {
    const values = new Map<string, string>([[ROLE_CREATE_DRAFT_KEY, JSON.stringify({
      avatarId: "avatar-current",
      actionId: "action-old",
      talkingVariantId: "talking-old",
    })]]);
    const dispatchEvent = vi.fn();
    vi.stubGlobal("window", {
      sessionStorage: {
        getItem: (key: string) => values.get(key) ?? null,
        setItem: (key: string, value: string) => values.set(key, value),
      },
      dispatchEvent,
    });
    vi.stubGlobal("CustomEvent", class<T> {
      detail: T;
      constructor(_name: string, init: { detail: T }) { this.detail = init.detail; }
    });

    completeRoleCreationResource({ kind: "action", id: "action-new" });

    expect(JSON.parse(values.get(ROLE_CREATE_DRAFT_KEY) ?? "{}")).toEqual({
      avatarId: "avatar-current",
      actionId: "action-new",
      talkingVariantId: null,
    });
    expect(dispatchEvent).toHaveBeenCalledOnce();
  });
});

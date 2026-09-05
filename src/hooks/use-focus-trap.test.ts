import { describe, expect, it } from "vitest";
import { resolveFocusTrapWrapTarget } from "./use-focus-trap";

describe("resolveFocusTrapWrapTarget", () => {
  const first = { id: "first" };
  const last = { id: "last" };
  const middle = { id: "middle" };

  it("wraps from the last element to the first on Tab", () => {
    expect(resolveFocusTrapWrapTarget(last, first, last, false)).toBe(first);
  });

  it("wraps from the first element to the last on Shift+Tab", () => {
    expect(resolveFocusTrapWrapTarget(first, first, last, true)).toBe(last);
  });

  it("does not wrap when focus is on a middle element", () => {
    expect(resolveFocusTrapWrapTarget(middle, first, last, false)).toBeNull();
    expect(resolveFocusTrapWrapTarget(middle, first, last, true)).toBeNull();
  });

  it("does not wrap forward from the first element", () => {
    expect(resolveFocusTrapWrapTarget(first, first, last, false)).toBeNull();
  });

  it("does not wrap backward from the last element", () => {
    expect(resolveFocusTrapWrapTarget(last, first, last, true)).toBeNull();
  });
});

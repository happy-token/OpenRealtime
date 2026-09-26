import { describe, expect, it, vi } from "vitest";
import { createMagicRingsContext } from "./magic-rings";

describe("createMagicRingsContext", () => {
  it("uses a working WebGL2 context", () => {
    const context = {} as WebGL2RenderingContext;
    const getContext = vi.fn(() => context);
    expect(createMagicRingsContext({ getContext } as unknown as HTMLCanvasElement)).toBe(context);
    expect(getContext).toHaveBeenCalledWith("webgl2", { alpha: true, antialias: false });
  });

  it("returns the CSS fallback path when context creation is blocked", () => {
    expect(createMagicRingsContext({ getContext: () => null } as unknown as HTMLCanvasElement)).toBeNull();
    expect(createMagicRingsContext({ getContext: () => { throw new Error("WebGL disabled"); } } as unknown as HTMLCanvasElement)).toBeNull();
  });
});

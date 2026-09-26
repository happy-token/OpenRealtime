import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import DismissModalPage from "@/app/@modal/[...catchAll]/page";

describe("modal routing", () => {
  it("clears an intercepted page when navigation leaves the modal route", () => {
    expect(renderToStaticMarkup(<DismissModalPage />)).toBe("");
  });
});

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import Folder from "./folder";

describe("Folder", () => {
  it("renders every supplied material as an accessible paper", () => {
    const html = renderToStaticMarkup(
      <Folder
        ariaLabel="展开柔和回应口型对齐"
        front={<span>柔和回应</span>}
        items={[<span key="1">一</span>, <span key="2">二</span>, <span key="3">三</span>, <span key="4">四</span>]}
        itemAriaLabels={["素材一", "素材二", "素材三", "素材四"]}
        open
      />,
    );

    expect(html).toContain('aria-expanded="true"');
    expect(html).toContain('aria-label="素材一"');
    expect(html).toContain('aria-label="素材三"');
    expect(html).toContain('aria-label="素材四"');
  });

  it("keeps collapsed materials hidden behind the front card", () => {
    const html = renderToStaticMarkup(
      <Folder
        ariaLabel="展开柔和回应口型对齐"
        front={<span>柔和回应</span>}
        items={[<span key="1">温柔问候</span>]}
        itemAriaLabels={["选择口型素材：温柔问候"]}
        selectedItemIndex={0}
        open={false}
      />,
    );

    expect(html).toContain('data-open="false"');
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain('aria-hidden="true"');
    expect(html).toContain('tabindex="-1"');
  });
});

import { describe, expect, it } from "vitest";
import { filterWorkbenchIdentityAssets, mergeWorkbenchIdentityAssets } from "./digital-human-identity-catalog";

describe("digital human identity catalog", () => {
  it("adds an authorized browser upload as a selectable saved identity", () => {
    const assets = mergeWorkbenchIdentityAssets(
      [{
        id: "reference-one",
        name: "参考一号",
        width: 512,
        height: 512,
        previewImageUrl: "/reference.jpg",
        sourceImageUrl: "/reference.jpg",
        origin: "项目参考",
        category: "reference",
      }],
      [{
        identityId: "custom-11111111-1111-4111-8111-111111111111",
        name: "我的主持人.png",
        dataUrl: "data:image/jpeg;base64,/9j/",
        sourceSha256: "digest",
        updatedAt: "2026-08-26T00:00:00.000Z",
      }],
    );

    expect(assets).toHaveLength(2);
    expect(assets[1]).toMatchObject({
      id: "custom-11111111-1111-4111-8111-111111111111",
      name: "我的主持人.png",
      sourceImageUrl: "data:image/jpeg;base64,/9j/",
      origin: "授权上传",
      category: "saved",
    });
  });

  it("filters by saved/reference category and a case-insensitive name or origin query", () => {
    const assets = [
      { id: "saved", name: "My Host", previewImageUrl: "/a.jpg", sourceImageUrl: "/a.jpg", origin: "授权上传", category: "saved" as const },
      { id: "reference", name: "Anchor", previewImageUrl: "/b.jpg", sourceImageUrl: "/b.jpg", origin: "OpenTalking", category: "reference" as const },
    ];

    expect(filterWorkbenchIdentityAssets(assets, "saved", "host").map((asset) => asset.id)).toEqual(["saved"]);
    expect(filterWorkbenchIdentityAssets(assets, "reference", "opentalking").map((asset) => asset.id)).toEqual(["reference"]);
    expect(filterWorkbenchIdentityAssets(assets, "all", "missing")).toEqual([]);
  });
});

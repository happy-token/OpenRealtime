type MarkdownNode = {
  type: string;
  value?: string;
  children?: MarkdownNode[];
  data?: { hProperties?: Record<string, unknown> };
};

/** Give article headings stable anchors for source Markdown fragment links. */
export function remarkDocumentHeadings() {
  return (tree: MarkdownNode) => {
    const used = new Set<string>();
    const text = (node: MarkdownNode): string => node.value ?? node.children?.map(text).join("") ?? "";
    const visit = (node: MarkdownNode) => {
      if (node.type === "heading") {
        const base = text(node).trim().toLowerCase()
          .replace(new RegExp("[^\\p{L}\\p{M}\\p{N}\\s_-]", "gu"), "")
          .replace(/\s/g, "-");
        let id = base;
        let suffix = 0;
        while (used.has(id)) id = `${base}-${++suffix}`;
        used.add(id);
        node.data = { ...node.data, hProperties: { ...node.data?.hProperties, id } };
      }
      node.children?.forEach(visit);
    };
    visit(tree);
  };
}

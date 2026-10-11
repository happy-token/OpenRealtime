import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";
import messages from "./i18n/en.json";
import { translate } from "@/components/language/language-provider";
import avatars from "@/data/published-avatar-catalog.json";
import roles from "@/data/published-role-catalog.json";

const chinese = /[\u3400-\u9fff]/;
const dictionary = messages as Record<string, string>;

function sources(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const file = path.join(directory, entry.name);
    return entry.isDirectory() ? sources(file) : /\.tsx?$/.test(file) && !file.includes(".test.") ? [file] : [];
  });
}

describe("English UI coverage", () => {
  it("has no Chinese in English translations", () => {
    expect(Object.entries(dictionary).filter(([, value]) => chinese.test(value))).toEqual([]);
  });
  it("covers every official role, persona and action name", () => {
    const labels = [
      ...roles.flatMap(role => [role.display_name, ...(role.persona_name ? [role.persona_name] : [])]),
      ...avatars.flatMap(avatar => [avatar.display_name, ...avatar.actions.flatMap(action => [action.display_name, ...action.talking_variants.map(variant => variant.display_name)])]),
    ];
    expect(labels.filter(label => chinese.test(translate(label, "en")))).toEqual([]);
  });
  it("requires fixed UI text and literal translation keys to be localized", () => {
    const missing: string[] = [];
    for (const file of [...sources("src/components"), ...sources("src/app")]) {
      const source = ts.createSourceFile(file, readFileSync(file, "utf8"), ts.ScriptTarget.Latest, true);
      const visit = (node: ts.Node) => {
        if (ts.isJsxText(node) && chinese.test(node.text)) missing.push(`${file}: ${node.text.trim()}`);
        if (ts.isCallExpression(node) && node.expression.getText(source) === "t" && node.arguments[0] && ts.isStringLiteral(node.arguments[0])) {
          const key = node.arguments[0].text;
          if (chinese.test(key) && !Object.hasOwn(dictionary, key)) missing.push(`${file}: ${key}`);
        }
        ts.forEachChild(node, visit);
      };
      visit(source);
    }
    expect(missing).toEqual([]);
  });
  it("preserves custom content and handles composed official labels and object-prototype names", () => {
    expect(translate("Private 自定义角色", "en")).toBe("Private 自定义角色");
    expect(translate("Private 自定义角色 · 冷艳夜色", "en")).toBe("Private 自定义角色 · 冷艳夜色");
    expect(translate("萨曼莎 · 冷艳夜色 · Lip Forcing", "en")).toBe("Samantha · Cool Night · Lip Forcing");
    expect(translate("constructor", "en")).toBe("constructor");
    expect(translate("__proto__", "en")).toBe("__proto__");
  });
});

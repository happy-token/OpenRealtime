import { describe, expect, it } from "vitest";
import { isLanguagePreference, resolveAppLanguage } from "./app-language";
import { translate } from "@/components/language/language-provider";

describe("application language", () => {
  it("follows the primary system language and uses English for unsupported languages", () => {
    expect(resolveAppLanguage("system", ["zh-TW", "en-US"])).toBe("zh-CN");
    expect(resolveAppLanguage("system", ["en-GB", "zh-CN"])).toBe("en");
    expect(resolveAppLanguage("system", ["fr-FR"])).toBe("en");
    expect(resolveAppLanguage("zh-CN", ["en-US"])).toBe("zh-CN");
  });
  it("accepts only supported preferences", () => {
    expect(isLanguagePreference("system")).toBe(true);
    expect(isLanguagePreference("zh-CN")).toBe(true);
    expect(isLanguagePreference("en")).toBe(true);
    expect(isLanguagePreference("fr")).toBe(false);
  });
  it("translates known UI copy and preserves unmatched content", () => {
    expect(translate("跟随系统", "en")).toBe("Follow system");
    expect(translate("角色", "zh-CN")).toBe("角色");
    expect(translate("My 自定义角色 123", "en")).toBe("My 自定义角色 123");
  });
});

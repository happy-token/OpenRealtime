import { describe, expect, it } from "vitest";
import { selectedDefaultTtsProvider } from "./default-role-voice";

describe("default role TTS provider", () => {
  const instances = [
    { id: "mine", capability: "tts", provider: "dashscope", enabled: true, connectionStatus: "passed" },
    { id: "shared", capability: "tts", provider: "doubao", enabled: true, connectionStatus: "passed" },
  ];
  const platformCredentials = [{ capability: "tts", provider: "doubao" }];

  it("prefers the user's selected instance over the platform selection", () => {
    expect(selectedDefaultTtsProvider({ instances, platformCredentials,
      selections: { tts: "mine" }, platformSelections: { tts: "shared" } })).toBe("dashscope");
  });

  it("uses the selected platform configuration when the user has no selection", () => {
    expect(selectedDefaultTtsProvider({ instances, platformCredentials,
      platformSelections: { tts: "env:doubao" } })).toBe("doubao");
  });

  it("does not silently substitute a different provider for an unavailable selection", () => {
    expect(selectedDefaultTtsProvider({ instances, platformCredentials,
      selections: { tts: "missing" }, platformSelections: { tts: "shared" } })).toBeNull();
  });

  it("uses the legacy fallback only when no explicit selection exists", () => {
    expect(selectedDefaultTtsProvider({ pipelineFallbacks: { tts: { provider: "dashscope" } } })).toBe("dashscope");
  });
});

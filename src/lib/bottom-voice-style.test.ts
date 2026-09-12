import { describe, expect, it } from "vitest";
import { bottomVoiceLevel, parseBottomVoiceStyle } from "./bottom-voice-style";

describe("bottom voice defaults and audio source states", () => {
  it("defaults new or invalid saved selections to B", () => {
    for (const value of [null, undefined, "", "cloud", {}, "unknown"]) expect(parseBottomVoiceStyle(value)).toBe("aurora");
    for (const value of ["ribbon", "aurora", "strings", "pulse"]) expect(parseBottomVoiceStyle(value)).toBe(value);
  });
  it("stops microphone visualization when muted but keeps audible AI output", () => {
    expect(bottomVoiceLevel("listening", .7, true, true)).toBe(0);
    expect(bottomVoiceLevel("speaking", .7, true, true)).toBe(.7);
    expect(bottomVoiceLevel("listening", .7, false, true)).toBe(.7);
  });
  it("does not invent speech energy when disconnected, thinking, or idle", () => {
    expect(bottomVoiceLevel("speaking", .7, false, false)).toBe(0);
    expect(bottomVoiceLevel("thinking", .7, false, true)).toBe(0);
    expect(bottomVoiceLevel("idle", .7, false, true)).toBe(0);
    expect(bottomVoiceLevel("speaking", Number.NaN, false, true)).toBe(0);
    expect(bottomVoiceLevel("speaking", 3, false, true)).toBe(1);
  });
});

import { describe, expect, it } from "vitest";
import { hasMatchingAudioSignature, hasMatchingImageSignature, hasMatchingVideoSignature } from "./media-signatures";

describe("media signatures", () => {
  it("recognizes supported normalized images", () => {
    expect(hasMatchingImageSignature("image/jpeg", Uint8Array.from([255, 216, 255]))).toBe(true);
    expect(hasMatchingImageSignature("image/png", Uint8Array.from([137, 80, 78, 71, 13, 10, 26, 10]))).toBe(true);
    expect(hasMatchingImageSignature("image/jpeg", Uint8Array.from([0, 1, 2]))).toBe(false);
  });

  it("recognizes MP4, QuickTime and WebM containers without trusting MIME alone", () => {
    const iso = Uint8Array.from([0, 0, 0, 24, 102, 116, 121, 112, 105, 115, 111, 109]);
    expect(hasMatchingVideoSignature("video/mp4", iso)).toBe(true);
    expect(hasMatchingVideoSignature("video/quicktime", iso)).toBe(true);
    expect(hasMatchingVideoSignature("video/webm", Uint8Array.from([0x1a, 0x45, 0xdf, 0xa3]))).toBe(true);
    expect(hasMatchingVideoSignature("video/mp4", Uint8Array.from([0, 1, 2, 3]))).toBe(false);
  });

  it("recognizes upload and browser-recorded audio containers", () => {
    const wav = Uint8Array.from([...Buffer.from("RIFF"), 0, 0, 0, 0, ...Buffer.from("WAVE")]);
    const m4a = Uint8Array.from([0, 0, 0, 24, ...Buffer.from("ftyp"), 0, 0, 0, 0]);
    expect(hasMatchingAudioSignature("audio/wav", wav)).toBe(true);
    expect(hasMatchingAudioSignature("audio/mpeg", Uint8Array.from(Buffer.from("ID3sample")))).toBe(true);
    expect(hasMatchingAudioSignature("audio/mp4", m4a)).toBe(true);
    expect(hasMatchingAudioSignature("audio/webm", Uint8Array.from([0x1a, 0x45, 0xdf, 0xa3]))).toBe(true);
    expect(hasMatchingAudioSignature("audio/ogg", Uint8Array.from(Buffer.from("OggS")))).toBe(true);
    expect(hasMatchingAudioSignature("audio/wav", Uint8Array.from(Buffer.from("not-a-wave")))).toBe(false);
  });
});

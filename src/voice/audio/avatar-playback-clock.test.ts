import { describe, expect, it } from "vitest";
import { AvatarPlaybackClock } from "./avatar-playback-clock";

describe("avatar media playback clock", () => {
  it("uses media time, freezes during stalls and caps position to supplied PCM", () => {
    const media = { volume: 1, currentTime: 50, paused: false, readyState: 4 };
    const clock = new AvatarPlaybackClock(7, "speech");
    clock.append(btoa("\0".repeat(2000)), 1000);
    expect(clock.read(media)).toBeNull();
    clock.start(media);
    media.currentTime = 50.3;
    expect(clock.read(media)?.playedAudioEndUs).toBe(300000);
    media.readyState = 1;
    media.currentTime = 50.5;
    expect(clock.read(media)?.playedAudioEndUs).toBe(300000);
    media.readyState = 4;
    media.currentTime = 52;
    expect(clock.read(media)?.playedAudioEndUs).toBe(1000000);
    expect(clock.read(media)?.speechId).toBe("speech");
  });

  it("does not fabricate progress when media time is unavailable", () => {
    const clock = new AvatarPlaybackClock(8, "next");
    clock.start({ volume: 1 });
    expect(clock.read({ volume: 1 })).toBeNull();
  });
});

import { afterEach, expect, it, vi } from "vitest";
import { getPlaybackActive, setPlaybackActive, subscribePlaybackActivity } from "./playback-activity";
afterEach(() => setPlaybackActive(false));
it("notifies on playback start and stop without repeating unchanged states", () => {
  const listener = vi.fn();
  const unsubscribe = subscribePlaybackActivity(listener);
  expect(getPlaybackActive()).toBe(false);
  setPlaybackActive(true);
  setPlaybackActive(true);
  expect(listener).toHaveBeenCalledTimes(1);
  expect(getPlaybackActive()).toBe(true);
  setPlaybackActive(false);
  expect(listener).toHaveBeenCalledTimes(2);
  unsubscribe();
  setPlaybackActive(true);
  expect(listener).toHaveBeenCalledTimes(2);
});

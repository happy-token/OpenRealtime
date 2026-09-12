// Shared observation of actual speaker playback; text generation does not activate it.
let active = false;
const listeners = new Set<() => void>();
export function setPlaybackActive(value: boolean) {
  if (active === value) return;
  active = value;
  listeners.forEach(listener => listener());
}
export function getPlaybackActive() { return active; }
export function subscribePlaybackActivity(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
export function getServerPlaybackActive() { return false; }

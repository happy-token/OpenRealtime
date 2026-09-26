export const NAVIGATION_START_EVENT = "openrealtime:navigation-start";

export function announceNavigationStart() {
  window.dispatchEvent(new Event(NAVIGATION_START_EVENT));
}

export function isRouteNavigation(destination: URL, current: URL) {
  return destination.origin === current.origin
    && (destination.pathname !== current.pathname || destination.search !== current.search);
}

export function shouldShowRouteLoading(destination: URL, current: URL) {
  if (!isRouteNavigation(destination, current)) return false;
  const inSettings = (path: string) => path === "/settings" || path.startsWith("/settings/");
  return !(inSettings(current.pathname) && inSettings(destination.pathname));
}

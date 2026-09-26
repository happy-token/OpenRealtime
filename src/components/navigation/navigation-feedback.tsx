"use client";

import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { shouldShowRouteLoading, NAVIGATION_START_EVENT } from "./navigation-events";
import { RouteLoading } from "./route-loading";

const NAVIGATION_TIMEOUT_MS = 10_000;

export function NavigationFeedback() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const locationKey = `${pathname}?${searchParams.toString()}`;
  const [pending, setPending] = useState(false);

  useEffect(() => setPending(false), [locationKey]);

  useEffect(() => {
    const beginNavigation = () => setPending(true);
    const handleClick = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const target = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>("a[href]") : null;
      if (!target || target.target || target.download) return;
      const destination = new URL(target.href, window.location.href);
      const current = new URL(window.location.href);
      if (!shouldShowRouteLoading(destination, current)) return;
      beginNavigation();
    };

    document.addEventListener("click", handleClick, true);
    window.addEventListener(NAVIGATION_START_EVENT, beginNavigation);
    return () => {
      document.removeEventListener("click", handleClick, true);
      window.removeEventListener(NAVIGATION_START_EVENT, beginNavigation);
    };
  }, []);

  useEffect(() => {
    if (!pending) return;
    const timeout = window.setTimeout(() => setPending(false), NAVIGATION_TIMEOUT_MS);
    return () => window.clearTimeout(timeout);
  }, [pending]);

  return pending ? <RouteLoading /> : null;
}

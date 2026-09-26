"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export const ROLE_CREATE_DRAFT_KEY = "openrealtime:role-create-draft:v2";

export type RoleCreationResource = {
  kind: "avatar" | "realtime" | "action" | "talking";
  id: string;
};

const RESOURCE_EVENT = "openrealtime:role-creation-resource";

type RoleCreationWorkbenchValue = {
  latestResource: RoleCreationResource | null;
  resourceRevision: number;
  completeResource: (resource: RoleCreationResource) => void;
};

const RoleCreationWorkbenchContext = createContext<RoleCreationWorkbenchValue>({
  latestResource: null,
  resourceRevision: 0,
  completeResource: () => undefined,
});

export function RoleCreationWorkbenchProvider({ children }: { children: ReactNode }) {
  const [latestResource, setLatestResource] = useState<RoleCreationResource | null>(null);
  const [resourceRevision, setResourceRevision] = useState(0);

  useEffect(() => {
    const handleResource = (event: Event) => {
      const resource = (event as CustomEvent<RoleCreationResource>).detail;
      if (!resource?.kind || !resource.id) return;
      setLatestResource(resource);
      setResourceRevision((revision) => revision + 1);
    };
    window.addEventListener(RESOURCE_EVENT, handleResource);
    return () => window.removeEventListener(RESOURCE_EVENT, handleResource);
  }, []);

  const completeResource = useCallback((resource: RoleCreationResource) => {
    completeRoleCreationResource(resource);
  }, []);

  const value = useMemo(() => ({ latestResource, resourceRevision, completeResource }), [completeResource, latestResource, resourceRevision]);
  return <RoleCreationWorkbenchContext.Provider value={value}>{children}</RoleCreationWorkbenchContext.Provider>;
}

export function completeRoleCreationResource(resource: RoleCreationResource) {
  if (typeof window === "undefined") return;
  try {
    const draft = JSON.parse(window.sessionStorage.getItem(ROLE_CREATE_DRAFT_KEY) ?? "{}") as Record<string, unknown>;
    const next = resource.kind === "avatar"
      ? { ...draft, avatarId: resource.id, actionId: null, talkingVariantId: null }
      : resource.kind === "action"
        ? { ...draft, actionId: resource.id, talkingVariantId: null }
        : resource.kind === "talking"
          ? { ...draft, talkingVariantId: resource.id }
          : draft;
    window.sessionStorage.setItem(ROLE_CREATE_DRAFT_KEY, JSON.stringify(next));
  } catch {
    // The event still updates a mounted workflow if storage is unavailable.
  }
  window.dispatchEvent(new CustomEvent<RoleCreationResource>(RESOURCE_EVENT, { detail: resource }));
}

export function useRoleCreationWorkbench() {
  return useContext(RoleCreationWorkbenchContext);
}

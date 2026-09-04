"use client";

import { useEffect, useRef, useState } from "react";
import { readJsonResponse } from "@/lib/http-json-response";
import { buildPersonaSwitchPayload } from "@/lib/persona-editor";
import type { AvatarPersonaProfile, PersonaSummary } from "@/lib/avatar-persona";

export type PersonaLinkState = "idle" | "loading" | "ready" | "unlinked" | "error";
export type PersonaOptionsState = "idle" | "loading" | "ready" | "error";
export type PersonaSwitchState = "idle" | "busy" | "error";

export interface UsePersonaLinkResult {
  linkedPersona: AvatarPersonaProfile | null;
  linkedPersonaState: PersonaLinkState;
  personaOptions: PersonaSummary[];
  personaOptionsState: PersonaOptionsState;
  switchState: PersonaSwitchState;
  switchNotice: string;
  switchPersona: (personaId: string) => Promise<void>;
}

/**
 * Fetches the Persona linked to an avatar, the full Persona list, and exposes
 * a mutator to switch the link. Shared by the drawer's Persona block and the
 * workbench quick-selector so both surfaces read/write through one code path.
 */
export function usePersonaLink(
  avatarId: string | null,
  avatarDisplayName: string,
  active: boolean,
): UsePersonaLinkResult {
  const [linkedPersona, setLinkedPersona] = useState<AvatarPersonaProfile | null>(null);
  const [linkedPersonaState, setLinkedPersonaState] = useState<PersonaLinkState>("idle");
  const [personaOptions, setPersonaOptions] = useState<PersonaSummary[]>([]);
  const [personaOptionsState, setPersonaOptionsState] = useState<PersonaOptionsState>("idle");
  const [switchState, setSwitchState] = useState<PersonaSwitchState>("idle");
  const [switchNotice, setSwitchNotice] = useState("");
  const avatarDisplayNameRef = useRef(avatarDisplayName);
  avatarDisplayNameRef.current = avatarDisplayName;

  useEffect(() => {
    if (!active || !avatarId) {
      setLinkedPersona(null);
      setLinkedPersonaState("idle");
      return;
    }
    const controller = new AbortController();
    setLinkedPersona(null);
    setLinkedPersonaState("loading");
    void fetch(`/api/avatars/${encodeURIComponent(avatarId)}/persona`, {
      cache: "no-store",
      signal: controller.signal,
    }).then(async (response) => {
      if (response.status === 404) {
        setLinkedPersonaState("unlinked");
        return;
      }
      if (!response.ok) throw new Error("Persona 配置读取失败");
      const payload = await readJsonResponse<{ profile?: AvatarPersonaProfile }>(response, "Persona 配置读取失败");
      if (!payload.profile) throw new Error("Persona 配置响应无效");
      setLinkedPersona(payload.profile);
      setLinkedPersonaState("ready");
    }).catch((error) => {
      if (error instanceof Error && error.name === "AbortError") return;
      setLinkedPersonaState("error");
    });
    return () => controller.abort();
  }, [active, avatarId]);

  useEffect(() => {
    if (!active) {
      setPersonaOptionsState("idle");
      return;
    }
    const controller = new AbortController();
    setPersonaOptionsState("loading");
    void fetch("/api/personas", { cache: "no-store", signal: controller.signal })
      .then((response) => readJsonResponse<{ personas?: PersonaSummary[] }>(response, "Persona 列表读取失败"))
      .then((payload) => {
        setPersonaOptions(payload.personas ?? []);
        setPersonaOptionsState("ready");
      })
      .catch((error) => {
        if (error instanceof Error && error.name === "AbortError") return;
        setPersonaOptionsState("error");
      });
    return () => controller.abort();
  }, [active]);

  async function switchPersona(personaId: string) {
    if (!avatarId) return;
    setSwitchState("busy");
    setSwitchNotice("");
    try {
      const response = await fetch(`/api/avatars/${encodeURIComponent(avatarId)}/persona`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildPersonaSwitchPayload(personaId, avatarDisplayNameRef.current)),
      });
      const payload = await readJsonResponse<{ profile?: AvatarPersonaProfile; error?: string }>(
        response,
        "Persona 切换失败",
      );
      if (!response.ok || !payload.profile) throw new Error(payload.error || "Persona 切换失败");
      setLinkedPersona(payload.profile);
      setLinkedPersonaState("ready");
      setSwitchState("idle");
    } catch (error) {
      setSwitchState("error");
      setSwitchNotice(error instanceof Error ? error.message : "Persona 切换失败");
    }
  }

  return {
    linkedPersona,
    linkedPersonaState,
    personaOptions,
    personaOptionsState,
    switchState,
    switchNotice,
    switchPersona,
  };
}

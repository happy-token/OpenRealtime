"use client";

import { Check } from "lucide-react";
import type { PersonaSummary } from "@/lib/avatar-persona";
import styles from "./identity-choice-grid.module.css";

export function PersonaChoiceGrid({
  personas,
  value,
  onChange,
  disabled = false,
}: {
  personas: readonly PersonaSummary[];
  value: string | null;
  onChange: (personaId: string | null) => void;
  disabled?: boolean;
}) {
  return <div className={styles.personaGrid} role="group" aria-label="选择人设">
    <button className={`${styles.personaCard} liquid-glass-surface`} type="button" data-selected={!value} aria-pressed={!value} disabled={disabled} onClick={() => onChange(null)}>
      <strong>默认助手</strong><span>使用角色默认的对话风格。</span>
      {!value ? <Check className={styles.check} aria-hidden="true" /> : null}
    </button>
    {personas.map((persona) => <button className={`${styles.personaCard} liquid-glass-surface`} key={persona.personaId} type="button" data-selected={value === persona.personaId} aria-pressed={value === persona.personaId} disabled={disabled} onClick={() => onChange(persona.personaId)}>
      <strong>{persona.personaName}</strong><span>{persona.intro || "尚未填写简介"}</span>
      {value === persona.personaId ? <Check className={styles.check} aria-hidden="true" /> : null}
    </button>)}
  </div>;
}

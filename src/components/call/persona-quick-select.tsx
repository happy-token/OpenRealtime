"use client";

import { FileText } from "lucide-react";

import { SelectMenu } from "@/components/ui/select-menu";
import { usePersonaLink } from "@/hooks/use-persona-link";
import { PERSONA_CREATE_OPTION_VALUE, personaSelectOptions } from "@/lib/avatar-persona";
import styles from "./persona-quick-select.module.css";

export function PersonaQuickSelect({
  avatarId,
  avatarDisplayName,
}: {
  avatarId: string | null;
  avatarDisplayName: string;
}) {
  const { linkedPersona, personaOptions, switchState, switchNotice, switchPersona } = usePersonaLink(
    avatarId,
    avatarDisplayName,
    true,
  );

  if (!avatarId) return null;

  return (
    <div className={styles.chip}>
      <span className={styles.chipIcon}>
        <FileText aria-hidden="true" />
      </span>
      <div className={styles.chipBody}>
        <small>Persona</small>
        <SelectMenu
          ariaLabel="选择 Persona"
          value={linkedPersona?.personaId ?? ""}
          options={personaSelectOptions(personaOptions, linkedPersona?.personaId ?? null)}
          disabled={switchState === "busy"}
          compact
          placement="top"
          onChange={(value) => {
            if (value === PERSONA_CREATE_OPTION_VALUE) {
              window.open(
                `/personas?avatar_id=${encodeURIComponent(avatarId)}&avatar_display_name=${encodeURIComponent(avatarDisplayName)}`,
                "_blank",
                "noreferrer",
              );
              return;
            }
            if (!value || value === linkedPersona?.personaId) return;
            void switchPersona(value);
          }}
        />
        {switchState === "error" && switchNotice ? (
          <span className={styles.notice} role="alert">{switchNotice}</span>
        ) : null}
      </div>
    </div>
  );
}

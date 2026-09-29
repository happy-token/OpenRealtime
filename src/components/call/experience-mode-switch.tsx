"use client";
import { useLanguage } from "@/components/language/language-provider";


import { AudioLines, CircleHelp, Video } from "lucide-react";
import type { KeyboardEvent } from "react";
import {
  EXPERIENCE_MODE_OPTIONS,
  type ExperienceMode,
} from "@/components/digital-human/types";

const MODE_ICONS = {
  voice: AudioLines,
  avatar: Video,
} as const;

interface ExperienceModeSwitchProps {
  value: ExperienceMode;
  onChange: (mode: ExperienceMode) => void;
  disabledModes?: ExperienceMode[];
  compact?: boolean;
  descriptionsAsTooltip?: boolean;
  ariaLabel?: string;
}

export function ExperienceModeSwitch({
  value,
  onChange,
  disabledModes = [],
  compact = false,
  descriptionsAsTooltip = false,
  ariaLabel = "展示模式",
}: ExperienceModeSwitchProps) {
  const { t } = useLanguage();
  function moveSelection(event: KeyboardEvent<HTMLButtonElement>) {
    const direction = event.key === "ArrowRight" || event.key === "ArrowDown"
      ? 1
      : event.key === "ArrowLeft" || event.key === "ArrowUp"
        ? -1
        : 0;
    if (!direction && event.key !== "Home" && event.key !== "End") return;
    const buttons = Array.from(
      event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') ?? [],
    );
    if (!buttons.length) return;
    event.preventDefault();
    const current = buttons.indexOf(event.currentTarget);
    const next = event.key === "Home"
      ? buttons[0]
      : event.key === "End"
        ? buttons.at(-1)
        : buttons[(current + direction + buttons.length) % buttons.length];
    next?.focus();
    const nextMode = next?.dataset.mode as ExperienceMode | undefined;
    if (nextMode) onChange(nextMode);
  }

  return (
    <div
      className="experience-mode-switch"
      data-compact={compact}
      role="radiogroup"
      aria-label={ariaLabel}
    >
      {EXPERIENCE_MODE_OPTIONS.map((option) => {
        const Icon = MODE_ICONS[option.id];
        const selected = value === option.id;
        return (
          <button
            type="button"
            role="radio"
            aria-checked={selected}
            aria-label={descriptionsAsTooltip ? `${option.label}：${option.description}` : option.label}
            data-active={selected}
            data-mode={option.id}
            tabIndex={selected ? 0 : -1}
            disabled={disabledModes.includes(option.id)}
            key={option.id}
            onClick={() => onChange(option.id)}
            onKeyDown={moveSelection}
          >
            <span className="experience-mode-icon" aria-hidden="true"><Icon /></span>
            <span>
              <strong>{t(option.label)}</strong>
              {descriptionsAsTooltip ? (
                <span
                  className="experience-mode-help"
                  data-tooltip={option.description}
                  title={option.description}
                  aria-hidden="true"
                >
                  <CircleHelp aria-hidden="true" />
                </span>
              ) : <small>{t(option.description)}</small>}
            </span>
          </button>
        );
      })}
    </div>
  );
}

"use client";

import { type ReactNode, useEffect, useRef, useState } from "react";

export interface SelectMenuOption<T extends string> {
  value: T;
  label: string;
  description?: string;
}

interface SelectMenuProps<T extends string> {
  value: T;
  options: readonly SelectMenuOption<T>[];
  ariaLabel: string;
  onChange: (value: T) => void;
  disabled?: boolean;
  compact?: boolean;
  placement?: "top" | "bottom";
  searchable?: boolean;
  renderOptionAction?: (option: SelectMenuOption<T>) => ReactNode;
  cardOptions?: boolean;
}

export function SelectMenu<T extends string>({
  value,
  options,
  ariaLabel,
  onChange,
  disabled = false,
  compact = false,
  placement = "bottom",
  searchable = false,
  renderOptionAction,
  cardOptions = false,
}: SelectMenuProps<T>) {
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const selectedIndex = Math.max(0, options.findIndex((option) => option.value === value));
  const selected = options[selectedIndex] ?? options[0];
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const visibleOptions = normalizedQuery
    ? options.filter((option) => (
      `${option.label} ${option.description ?? ""}`.toLocaleLowerCase().includes(normalizedQuery)
    ))
    : options;

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setActiveIndex(selectedIndex);
    if (searchable) window.setTimeout(() => searchRef.current?.focus(), 0);
    const handlePointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open, searchable, selectedIndex]);

  function moveActive(direction: 1 | -1) {
    if (!visibleOptions.length) return;
    const next = (activeIndex + direction + visibleOptions.length) % visibleOptions.length;
    setActiveIndex(next);
    optionRefs.current[next]?.focus();
  }

  function select(option: SelectMenuOption<T>) {
    onChange(option.value);
    setOpen(false);
  }

  return (
    <div
      className={`select-menu ${compact ? "select-menu-compact" : ""} ${cardOptions ? "select-menu-cards" : ""} select-menu-${placement}`}
      ref={rootRef}
    >
      <button
        type="button"
        className="select-menu-trigger"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            setOpen(true);
            setTimeout(() => optionRefs.current[selectedIndex]?.focus(), 0);
          }
        }}
      >
        <span>{selected?.label}</span>
        <svg viewBox="0 0 20 20" aria-hidden="true">
          <path d="m6 8 4 4 4-4" />
        </svg>
      </button>
      {open && (
        <div
          className={`select-menu-popover ${renderOptionAction ? "select-menu-with-actions" : ""}`}
          role="listbox"
          aria-label={ariaLabel}
        >
          {searchable && (
            <div className="select-menu-search-wrap">
              <svg viewBox="0 0 20 20" aria-hidden="true">
                <circle cx="8.5" cy="8.5" r="4.75" />
                <path d="m12 12 4 4" />
              </svg>
              <input
                ref={searchRef}
                className="select-menu-search"
                value={query}
                placeholder="搜索音色或场景"
                aria-label={`搜索${ariaLabel}`}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setActiveIndex(0);
                }}
                onKeyDown={(event) => {
                  if (event.key === "ArrowDown") {
                    event.preventDefault();
                    optionRefs.current[0]?.focus();
                  }
                }}
              />
              {query && (
                <button
                  type="button"
                  className="select-menu-search-clear"
                  aria-label="清除搜索"
                  onClick={() => {
                    setQuery("");
                    searchRef.current?.focus();
                  }}
                >
                  ×
                </button>
              )}
            </div>
          )}
          {visibleOptions.map((option, index) => (
            <div
              className="select-menu-option"
              data-active={index === activeIndex ? "true" : "false"}
              data-selected={option.value === value ? "true" : "false"}
              key={option.value}
            >
              <button
                type="button"
                role="option"
                aria-selected={option.value === value}
                className="select-menu-option-select"
                ref={(node) => { optionRefs.current[index] = node; }}
                onFocus={() => setActiveIndex(index)}
                onClick={() => select(option)}
                onKeyDown={(event) => {
                  if (event.key === "ArrowDown") {
                    event.preventDefault();
                    moveActive(1);
                  } else if (event.key === "ArrowUp") {
                    event.preventDefault();
                    moveActive(-1);
                  } else if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    select(option);
                  }
                }}
              >
                <span className="select-menu-check" aria-hidden="true">
                  {option.value === value ? "✓" : ""}
                </span>
                <span className="select-menu-option-copy">
                  <strong>{option.label}</strong>
                  {option.description && <small>{option.description}</small>}
                </span>
              </button>
              {renderOptionAction?.(option)}
            </div>
          ))}
          {visibleOptions.length === 0 && (
            <div className="select-menu-empty">没有匹配的音色</div>
          )}
        </div>
      )}
    </div>
  );
}

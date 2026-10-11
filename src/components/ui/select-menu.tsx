"use client";
import { useLanguage } from "@/components/language/language-provider";


import { type ReactNode, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

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
  fullWidth?: boolean;
  placement?: "top" | "bottom";
  searchable?: boolean;
  renderOptionAction?: (option: SelectMenuOption<T>) => ReactNode;
  cardOptions?: boolean;
  localizeLabels?: boolean;
  triggerContent?: ReactNode;
  triggerRole?: "combobox";
}

export function SelectMenu<T extends string>({
  value,
  options,
  ariaLabel,
  onChange,
  disabled = false,
  compact = false,
  fullWidth = false,
  placement = "bottom",
  searchable = false,
  renderOptionAction,
  cardOptions = false,
  localizeLabels = false,
  triggerContent,
  triggerRole,
}: SelectMenuProps<T>) {
  const { t } = useLanguage();
  const listboxId = useId();
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const [popoverPosition, setPopoverPosition] = useState({ left: 0, top: 0, width: 194, maxHeight: 286, side: "bottom" });
  const searchRef = useRef<HTMLInputElement>(null);
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const selectedIndex = Math.max(0, options.findIndex((option) => option.value === value));
  const selected = options[selectedIndex] ?? options[0];
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const visibleOptions = normalizedQuery
    ? options.filter((option) => (
      `${option.label} ${option.description ?? ""} ${localizeLabels ? t(option.label) + " " + t(option.description ?? "") : ""}`.toLocaleLowerCase().includes(normalizedQuery)
    ))
    : options;

  useLayoutEffect(() => {
    if (!open || !fullWidth) return;
    const updatePosition = () => {
      const rect = rootRef.current?.getBoundingClientRect();
      if (!rect) return;
      const below = window.innerHeight - rect.bottom - 15;
      const above = rect.top - 15;
      const useTop = placement === "top" || (below < 160 && above > below);
      const width = Math.min(Math.max(194, rect.width), window.innerWidth - 16);
      setPopoverPosition({
        left: Math.max(8, Math.min(rect.right - width, window.innerWidth - width - 8)),
        top: useTop ? rect.top - 7 : rect.bottom + 7,
        width,
        side: useTop ? "top" : "bottom",
        maxHeight: Math.max(80, Math.min(286, useTop ? above : below)),
      });
    };
    updatePosition();
    window.addEventListener("resize", updatePosition);
    document.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("resize", updatePosition);
      document.removeEventListener("scroll", updatePosition, true);
    };
  }, [open, fullWidth, placement]);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setActiveIndex(selectedIndex);
    if (searchable) window.setTimeout(() => searchRef.current?.focus(), 0);
    const handlePointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node) && !popoverRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); setOpen(false); }
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

  const popover = open && (
    <div
      ref={popoverRef}
      data-side={fullWidth ? popoverPosition.side : undefined}
      className={`select-menu-popover ${renderOptionAction ? "select-menu-with-actions" : ""}`}
      style={fullWidth ? { position: "fixed", zIndex: 10000, left: popoverPosition.left, top: popoverPosition.top, right: "auto", bottom: "auto", width: popoverPosition.width, maxHeight: popoverPosition.maxHeight } : undefined}
      role="listbox"
      id={listboxId}
      aria-label={t(ariaLabel)}
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
            placeholder={t("搜索音色或场景")}
            aria-label={t("搜索") + (ariaLabel) + ""}
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
              aria-label={t("清除搜索")}
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
              <strong>{localizeLabels ? t(option.label) : option.label}</strong>
              {option.description && <small>{localizeLabels ? t(option.description) : option.description}</small>}
            </span>
          </button>
          {renderOptionAction?.(option)}
        </div>
      ))}
      {visibleOptions.length === 0 && (
        <div className="select-menu-empty">{t("没有匹配的音色")}</div>
      )}
    </div>
  );

  return (
    <div
      className={`select-menu ${compact ? "select-menu-compact" : ""} ${fullWidth ? "select-menu-field" : ""} ${cardOptions ? "select-menu-cards" : ""} select-menu-${placement}`}
      ref={rootRef}
    >
      <button
        type="button"
        className="select-menu-trigger"
        role={triggerRole}
        data-value={value}
        aria-label={t(ariaLabel)}
        aria-haspopup="listbox"
        aria-controls={listboxId}
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
        <span>{triggerContent ?? (selected && (localizeLabels ? t(selected.label) : selected.label))}</span>
        <svg viewBox="0 0 20 20" aria-hidden="true">
          <path d="m6 8 4 4 4-4" />
        </svg>
      </button>
      {fullWidth && open ? createPortal(popover, rootRef.current?.closest("dialog") ?? document.body) : popover}
    </div>
  );
}

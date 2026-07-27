import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { useEffect, useRef, useState } from "react";
import { useLocation } from "wouter";

import { getAllListeners } from "../../api/endpoints";
import { useManifests } from "../../hooks/use-manifests";
import { queryKeys } from "../../lib/query-keys";
import { statusToKind } from "../../utils/status";
import { StatusShape } from "../shared/status-shape";
import styles from "./command-palette.module.css";
import {
  buildActionItems,
  buildAppItems,
  buildHandlerItems,
  buildStaticPageItems,
  KIND_LABEL,
  KIND_ORDER,
  matchesQuery,
  type PaletteItem,
  type PaletteItemKind,
} from "./palette-items";

const PALETTE_STALE_TIME_MS = 300_000;

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
}

export function CommandPalette({ open, onClose }: CommandPaletteProps) {
  const [, navigate] = useLocation();
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  const resultsRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<Element | null>(null);

  const { data: allManifests = [] } = useManifests();
  // Palette data changes infrequently and is only fetched when open — 5min staleTime
  // avoids refetching on every open while keeping results reasonably fresh.
  const { data: listeners } = useQuery({
    queryKey: queryKeys.allListenersPalette(),
    queryFn: ({ signal }) => getAllListeners(undefined, signal),
    enabled: open,
    staleTime: PALETTE_STALE_TIME_MS,
  });

  useEffect(() => {
    if (!open) return;
    triggerRef.current = document.activeElement;
    setQuery("");
    setSelectedIndex(-1);
    requestAnimationFrame(() => {
      inputRef.current?.focus();
    });

    const handleDocKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    };
    document.addEventListener("keydown", handleDocKeyDown);
    return () => {
      document.removeEventListener("keydown", handleDocKeyDown);
      (triggerRef.current as HTMLElement | null)?.focus();
    };
  }, [open, onClose]);

  if (!open) return null;

  const pageItems = buildStaticPageItems(navigate);
  const actionItems = buildActionItems(allManifests, onClose);
  const appItems = buildAppItems(allManifests, navigate, onClose);
  const handlerItems = buildHandlerItems(listeners ?? [], navigate, onClose);

  const allItems: PaletteItem[] = [...pageItems, ...appItems, ...handlerItems, ...actionItems];
  // Group and filter
  const filtered = allItems.filter((item) => matchesQuery(item, query));

  // Build sections: only include kinds with results
  const sections: { kind: PaletteItemKind; items: PaletteItem[] }[] = KIND_ORDER.map((kind) => ({
    kind,
    items: filtered.filter((item) => item.kind === kind),
  })).filter((s) => s.items.length > 0);

  // Flat ordered results for keyboard navigation
  const flatResults = sections.flatMap((s) => s.items);
  const flatIndexMap = new Map(flatResults.map((item, i) => [item, i] as const));

  function handleKeyDown(e: ReactKeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (selectedIndex < flatResults.length - 1) setSelectedIndex(selectedIndex + 1);
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      if (selectedIndex > 0) setSelectedIndex(selectedIndex - 1);
      else setSelectedIndex(-1);
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      if (selectedIndex >= 0 && selectedIndex < flatResults.length) {
        flatResults[selectedIndex].action();
      }
    }
  }

  const isEmpty = flatResults.length === 0;

  return (
    <>
      <div className={styles.backdrop} aria-hidden="true" data-testid="cmd-palette-backdrop" onClick={onClose} />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        className={styles.palette}
        data-testid="cmd-palette"
      >
        <div
          tabIndex={0}
          aria-hidden="true"
          className={styles.focusTrap}
          onFocus={() => {
            const buttons = resultsRef.current?.querySelectorAll<HTMLElement>("button");
            const last = buttons && buttons.length > 0 ? buttons[buttons.length - 1] : null;
            (last ?? inputRef.current)?.focus();
          }}
        />

        <div className={styles.inputWrap}>
          <svg className={styles.searchIcon} width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
            <circle cx="6.5" cy="6.5" r="5" fill="none" stroke="currentColor" strokeWidth="1.5" />
            <line x1="10.5" y1="10.5" x2="14" y2="14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          <input
            ref={inputRef}
            type="text"
            className={styles.input}
            placeholder="Search apps, handlers, pages, actions…"
            value={query}
            onInput={(e) => {
              setQuery((e.target as HTMLInputElement).value);
              setSelectedIndex(-1);
            }}
            onKeyDown={handleKeyDown}
            aria-label="Search command palette"
            aria-autocomplete="list"
            aria-controls="cmd-palette-results"
            aria-activedescendant={selectedIndex >= 0 ? `cmd-option-${flatResults[selectedIndex]?.id}` : undefined}
            autoComplete="off"
            spellCheck={false}
          />
        </div>

        <div
          ref={resultsRef}
          id="cmd-palette-results"
          className={styles.results}
          role="listbox"
          aria-label="Command palette results"
          data-testid="cmd-palette-results"
        >
          {isEmpty && (
            <div className={styles.empty} data-testid="cmd-palette-empty">
              {query ? `No results for "${query}"` : "No items available"}
            </div>
          )}
          {sections.map((section) => (
            <div key={section.kind} className={styles.section} data-testid={`cmd-section-${section.kind}`}>
              <div className={styles.sectionHeader}>{KIND_LABEL[section.kind]}</div>
              {section.items.map((item) => {
                const flatIdx = flatIndexMap.get(item) ?? -1;
                const isActive = flatIdx === selectedIndex;
                return (
                  <button
                    key={item.id}
                    id={`cmd-option-${item.id}`}
                    type="button"
                    role="option"
                    aria-selected={isActive}
                    className={clsx(styles.result, isActive && styles.resultActive)}
                    data-testid={`cmd-result-${item.id}`}
                    onClick={() => item.action()}
                  >
                    <span className={styles.resultLabel}>
                      {item.status !== undefined && <StatusShape kind={statusToKind(item.status)} size={8} />}
                      {item.label}
                    </span>
                    {item.sub && <span className={styles.resultSub}>{item.sub}</span>}
                    <span className={styles.chip}>{item.kind}</span>
                  </button>
                );
              })}
            </div>
          ))}
        </div>

        <div tabIndex={0} aria-hidden="true" className={styles.focusTrap} onFocus={() => inputRef.current?.focus()} />

        <div className={styles.footer} aria-hidden="true" data-testid="cmd-palette-footer">
          <span>
            <kbd>↑↓</kbd> navigate
          </span>
          <span>
            <kbd>↵</kbd> select
          </span>
          <span>
            <kbd>esc</kbd> close
          </span>
        </div>
      </div>
    </>
  );
}

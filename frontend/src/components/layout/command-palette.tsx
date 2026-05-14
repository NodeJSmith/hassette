import { useEffect, useRef } from "preact/hooks";
import { useLocation } from "wouter";
import clsx from "clsx";
import { getAllListeners, reloadApp, stopApp } from "../../api/endpoints";
import type { AppManifest, ListenerData } from "../../api/endpoints";
import { useApi } from "../../hooks/use-api";
import { useSignal } from "../../hooks/use-signal";
import { useAppState } from "../../state/context";
import { statusToKind } from "../../utils/status";
import { StatusShape } from "../shared/status-shape";
import styles from "./command-palette.module.css";

// ---- Types ----

type PaletteItemKind = "page" | "app" | "instance" | "handler" | "action";

interface PaletteItem {
  id: string;
  kind: PaletteItemKind;
  label: string;
  sub?: string;
  status?: string;
  action: () => void;
}

// ---- Static items ----

function buildStaticPageItems(navigate: (path: string) => void): PaletteItem[] {
  return [
    {
      id: "page-apps",
      kind: "page",
      label: "apps",
      sub: "/apps",
      action: () => navigate("/apps"),
    },
    {
      id: "page-handlers",
      kind: "page",
      label: "handlers",
      sub: "/handlers",
      action: () => navigate("/handlers"),
    },
    {
      id: "page-logs",
      kind: "page",
      label: "logs",
      sub: "/logs",
      action: () => navigate("/logs"),
    },
    {
      id: "page-config",
      kind: "page",
      label: "config",
      sub: "/config",
      action: () => navigate("/config"),
    },
  ];
}

function buildActionItems(
  manifests: AppManifest[],
  onClose: () => void,
): PaletteItem[] {
  return [
    {
      id: "action-reload-all",
      kind: "action",
      label: "Reload all apps",
      action: () => {
        const running = manifests.filter((m) => m.status === "running");
        void Promise.allSettled(running.map((m) => reloadApp(m.app_key)));
        onClose();
      },
    },
    {
      id: "action-stop-failing",
      kind: "action",
      label: "Stop all failing",
      action: () => {
        const failing = manifests.filter((m) => m.status === "failed" || m.status === "crashed");
        void Promise.allSettled(failing.map((m) => stopApp(m.app_key)));
        onClose();
      },
    },
    {
      id: "action-open-docs",
      kind: "action",
      label: "Open docs",
      action: () => {
        window.open("https://hassette.readthedocs.io", "_blank", "noreferrer");
        onClose();
      },
    },
  ];
}

function buildAppItems(manifests: AppManifest[], navigate: (path: string) => void, onClose: () => void): PaletteItem[] {
  const items: PaletteItem[] = [];
  const sorted = [...manifests].sort((a, b) => a.app_key.localeCompare(b.app_key));
  for (const m of sorted) {
    items.push({
      id: `app-${m.app_key}`,
      kind: "app",
      label: m.display_name,
      sub: m.app_key,
      status: m.status,
      action: () => {
        navigate(`/apps/${m.app_key}`);
        onClose();
      },
    });
    // Multi-instance apps: add an instance item per child
    if (m.instance_count > 1) {
      for (const inst of m.instances ?? []) {
        items.push({
          id: `instance-${m.app_key}-${inst.index}`,
          kind: "instance",
          label: inst.instance_name,
          sub: `${m.app_key} · #${inst.index}`,
          status: inst.status,
          action: () => {
            navigate(`/apps/${m.app_key}?instance=${inst.index}`);
            onClose();
          },
        });
      }
    }
  }
  return items;
}

function buildHandlerItems(
  listeners: ListenerData[],
  navigate: (path: string) => void,
  onClose: () => void,
): PaletteItem[] {
  return listeners.map((l) => ({
    id: `handler-${l.listener_id}`,
    kind: "handler" as const,
    label: l.handler_method,
    sub: `${l.app_key} · ${l.topic}`,
    action: () => {
      navigate(`/apps/${l.app_key}/handlers/h-${l.listener_id}`);
      onClose();
    },
  }));
}

// ---- Filtering ----

function matchesQuery(item: PaletteItem, query: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  if (item.label.toLowerCase().includes(q)) return true;
  if (item.sub?.toLowerCase().includes(q)) return true;
  if (item.kind.toLowerCase().includes(q)) return true;
  return false;
}

// ---- Component ----

const KIND_ORDER: PaletteItemKind[] = ["page", "app", "instance", "handler", "action"];

const KIND_LABEL: Record<PaletteItemKind, string> = {
  page: "pages",
  app: "apps",
  instance: "instances",
  handler: "handlers",
  action: "actions",
};

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
}

export function CommandPalette({ open, onClose }: CommandPaletteProps) {
  const [, navigate] = useLocation();
  const query = useSignal("");
  const selectedIndex = useSignal(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  const resultsRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<Element | null>(null);

  const { manifests } = useAppState();
  const allManifests = manifests.value;
  const listenersApi = useApi(getAllListeners, [], { lazy: true });

  useEffect(() => {
    if (!open) return;
    triggerRef.current = document.activeElement;
    query.value = "";
    selectedIndex.value = -1;
    void listenersApi.refetch();
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
  const handlerItems = buildHandlerItems(listenersApi.data.value ?? [], navigate, onClose);

  const allItems: PaletteItem[] = [...pageItems, ...appItems, ...handlerItems, ...actionItems];
  // Group and filter
  const filtered = allItems.filter((item) => matchesQuery(item, query.value));

  // Build sections: only include kinds with results
  const sections: { kind: PaletteItemKind; items: PaletteItem[] }[] = KIND_ORDER
    .map((kind) => ({ kind, items: filtered.filter((item) => item.kind === kind) }))
    .filter((s) => s.items.length > 0);

  // Flat ordered results for keyboard navigation
  const flatResults = sections.flatMap((s) => s.items);
  const flatIndexMap = new Map(flatResults.map((item, i) => [item, i] as const));

  function handleKeyDown(e: KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (selectedIndex.value < flatResults.length - 1) selectedIndex.value += 1;
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      if (selectedIndex.value > 0) selectedIndex.value -= 1;
      else selectedIndex.value = -1;
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      if (selectedIndex.value >= 0 && selectedIndex.value < flatResults.length) {
        flatResults[selectedIndex.value].action();
      }
    }
  }

  const isEmpty = flatResults.length === 0;

  return (
    <>
      {/* Backdrop */}
      <div
        class={styles.backdrop}
        aria-hidden="true"
        data-testid="cmd-palette-backdrop"
        onClick={onClose}
      />
      {/* Panel */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        class={styles.palette}
        data-testid="cmd-palette"
      >
        {/* Top sentinel — catches Shift+Tab from search input, wraps focus to last result */}
        <div
          tabIndex={0}
          aria-hidden="true"
          style="position:absolute;width:1px;height:1px;overflow:hidden;opacity:0"
          onFocus={() => {
            // Focus arrived here via Shift+Tab from the search input.
            // Move to the last focusable result button inside the results list,
            // or back to the search input itself when no results exist.
            const buttons = resultsRef.current?.querySelectorAll<HTMLElement>("button");
            const last = buttons && buttons.length > 0 ? buttons[buttons.length - 1] : null;
            (last ?? inputRef.current)?.focus();
          }}
        />

        {/* Search input */}
        <div class={styles.inputWrap}>
          <svg
            class={styles.searchIcon}
            width="16"
            height="16"
            viewBox="0 0 16 16"
            aria-hidden="true"
          >
            <circle cx="6.5" cy="6.5" r="5" fill="none" stroke="currentColor" stroke-width="1.5" />
            <line x1="10.5" y1="10.5" x2="14" y2="14" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
          </svg>
          <input
            ref={inputRef}
            type="text"
            class={styles.input}
            placeholder="Search apps, handlers, pages, actions…"
            value={query.value}
            onInput={(e) => {
              query.value = (e.target as HTMLInputElement).value;
              selectedIndex.value = -1;
            }}
            onKeyDown={handleKeyDown}
            aria-label="Search command palette"
            aria-autocomplete="list"
            aria-controls="cmd-palette-results"
            autocomplete="off"
            spellcheck={false}
          />
        </div>

        {/* Results */}
        <div
          ref={resultsRef}
          id="cmd-palette-results"
          class={styles.results}
          role="listbox"
          aria-label="Command palette results"
          data-testid="cmd-palette-results"
        >
          {isEmpty && (
            <div class={styles.empty} data-testid="cmd-palette-empty">
              {query.value ? `No results for "${query.value}"` : "No items available"}
            </div>
          )}
          {sections.map((section) => (
            <div key={section.kind} class={styles.section} data-testid={`cmd-section-${section.kind}`}>
              <div class={styles.sectionHeader}>{KIND_LABEL[section.kind]}</div>
              {section.items.map((item) => {
                const flatIdx = flatIndexMap.get(item) ?? -1;
                const isActive = flatIdx === selectedIndex.value;
                return (
                  <button
                    key={item.id}
                    type="button"
                    role="option"
                    aria-selected={isActive}
                    class={clsx(styles.result, isActive && styles.resultActive)}
                    data-testid={`cmd-result-${item.id}`}
                    onClick={() => item.action()}
                  >
                    <span class={styles.resultLabel}>
                      {item.status !== undefined && (
                        <StatusShape kind={statusToKind(item.status)} size={8} />
                      )}
                      {item.label}
                    </span>
                    {item.sub && (
                      <span class={styles.resultSub}>{item.sub}</span>
                    )}
                    <span class={styles.chip}>{item.kind}</span>
                  </button>
                );
              })}
            </div>
          ))}
        </div>

        {/* Bottom sentinel — catches Tab from last result, wraps focus back to search input */}
        <div
          tabIndex={0}
          aria-hidden="true"
          style="position:absolute;width:1px;height:1px;overflow:hidden;opacity:0"
          onFocus={() => {
            inputRef.current?.focus();
          }}
        />

        {/* Footer */}
        <div class={styles.footer} aria-hidden="true" data-testid="cmd-palette-footer">
          <span><kbd>↑↓</kbd> navigate</span>
          <span><kbd>↵</kbd> select</span>
          <span><kbd>esc</kbd> close</span>
        </div>
      </div>
    </>
  );
}

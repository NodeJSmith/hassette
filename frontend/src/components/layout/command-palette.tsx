import { useEffect, useRef } from "preact/hooks";
import { useLocation } from "wouter";
import { getAllListeners, getManifests, reloadApp, stopApp } from "../../api/endpoints";
import type { AppManifest, ListenerData } from "../../api/endpoints";
import { useApi } from "../../hooks/use-api";
import { statusToKind } from "../../utils/status";
import { StatusShape } from "../shared/status-shape";
import { signal } from "@preact/signals";

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
      id: "page-overview",
      kind: "page",
      label: "Overview",
      sub: "/",
      action: () => navigate("/"),
    },
    {
      id: "page-logs",
      kind: "page",
      label: "Logs",
      sub: "/logs",
      action: () => navigate("/logs"),
    },
    {
      id: "page-config",
      kind: "page",
      label: "Config",
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
  for (const m of manifests) {
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
            navigate(`/apps/${m.app_key}/${inst.index}`);
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
      navigate(`/apps/${l.app_key}?focus=${l.handler_method}`);
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
  const query = useRef(signal("")).current;
  const selectedIndex = useRef(signal(-1)).current;
  const inputRef = useRef<HTMLInputElement>(null);
  const triggerRef = useRef<Element | null>(null);

  const manifests = useApi(getManifests);
  const allManifests = manifests.data.value?.manifests ?? [];
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

  // Build full item list
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
        class="ht-cmd-palette__backdrop"
        aria-hidden="true"
        onClick={onClose}
      />
      {/* Panel */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        class="ht-cmd-palette"
      >
        {/* Search input */}
        <div class="ht-cmd-palette__input-wrap">
          <svg
            class="ht-cmd-palette__search-icon"
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
            class="ht-cmd-palette__input"
            placeholder="Search apps, handlers, pages, actions…"
            value={query.value}
            onInput={(e) => {
              query.value = (e.target as HTMLInputElement).value;
              selectedIndex.value = -1;
            }}
            onKeyDown={handleKeyDown}
            aria-label="Search command palette"
            aria-autocomplete="list"
            aria-controls="ht-cmd-palette-results"
            autocomplete="off"
            spellcheck={false}
          />
        </div>

        {/* Results */}
        <div
          id="ht-cmd-palette-results"
          class="ht-cmd-palette__results"
          role="listbox"
          aria-label="Command palette results"
        >
          {isEmpty && (
            <div class="ht-cmd-palette__empty">{query.value ? `No results for "${query.value}"` : "No items available"}</div>
          )}
          {sections.map((section) => (
            <div key={section.kind} class="ht-cmd-palette__section">
              <div class="ht-cmd-palette__section-header">{KIND_LABEL[section.kind]}</div>
              {section.items.map((item) => {
                const flatIdx = flatResults.indexOf(item);
                const isActive = flatIdx === selectedIndex.value;
                return (
                  <button
                    key={item.id}
                    type="button"
                    role="option"
                    aria-selected={isActive}
                    class={`ht-cmd-palette__result${isActive ? " ht-cmd-palette__result--active" : ""}`}
                    onClick={() => item.action()}
                  >
                    <span class="ht-cmd-palette__result-label">
                      {item.status !== undefined && (
                        <StatusShape kind={statusToKind(item.status)} size={8} />
                      )}
                      {item.label}
                    </span>
                    {item.sub && (
                      <span class="ht-cmd-palette__result-sub">{item.sub}</span>
                    )}
                    <span class="ht-cmd-palette__chip">{item.kind}</span>
                  </button>
                );
              })}
            </div>
          ))}
        </div>

        {/* Footer */}
        <div class="ht-cmd-palette__footer" aria-hidden="true">
          <span><kbd>↑↓</kbd> navigate</span>
          <span><kbd>↵</kbd> select</span>
          <span><kbd>esc</kbd> close</span>
        </div>
      </div>
    </>
  );
}

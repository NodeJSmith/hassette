import type { MouseEvent as ReactMouseEvent } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "wouter";

import type { LogEntry } from "@/api/endpoints";
import { Drawer, DrawerContentUnstyled, DrawerOverlay, DrawerTitle } from "@/components/ui/drawer";
import { BREAKPOINT_MOBILE, BREAKPOINT_TABLET, useMediaQuery } from "@/hooks/use-media-query";
import { cn } from "@/lib/utils";
import { appDetailPath } from "@/utils/app-routes";
import { formatTimestamp } from "@/utils/format";

import { COPY_CONFIRM_MS, DETAIL_DRAWER_ID, getLogLevelStyle } from "./constants";
import { ExecutionIdLink } from "./execution-id-link";
import type { RowKey } from "./types";
import { rowKey } from "./types";

function levelSurfaceClass(level: string): string | undefined {
  return getLogLevelStyle(level)?.drawerSurface;
}

function levelTextClass(level: string): string | undefined {
  return getLogLevelStyle(level)?.drawerTone;
}

interface Props {
  selectedKey: RowKey | null;
  entries: readonly LogEntry[];
  onClose: () => void;
  onNavigate: (key: RowKey) => void;
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(
    async (e: ReactMouseEvent) => {
      e.stopPropagation();
      try {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => {
          setCopied(false);
        }, COPY_CONFIRM_MS);
      } catch {
        /* clipboard unavailable */
      }
    },
    [text],
  );

  return (
    <button
      type="button"
      className="shrink-0 cursor-pointer rounded-sm border-none bg-transparent p-0 text-[length:var(--text-mono-sm)] text-foreground-faint transition-colors hover:text-foreground-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
      onClick={handleCopy}
      aria-label={label}
      title={copied ? "Copied" : label}
    >
      {copied ? "✓" : "⧉"}
    </button>
  );
}

export function LogDetailDrawer({ selectedKey, entries, onClose, onNavigate }: Props) {
  const isMobile = useMediaQuery(BREAKPOINT_MOBILE);
  const isTablet = useMediaQuery(BREAKPOINT_TABLET);
  const drawerRef = useRef<HTMLDivElement>(null);

  const entry = selectedKey ? (entries.find((e) => rowKey(e) === selectedKey) ?? null) : null;
  const currentIndex = entry ? entries.findIndex((e) => rowKey(e) === selectedKey) : -1;
  const isFilteredOut = selectedKey !== null && entry === null;

  const navigatePrev = useCallback(() => {
    if (currentIndex <= 0) return;
    onNavigate(rowKey(entries[currentIndex - 1]));
  }, [currentIndex, entries, onNavigate]);

  const navigateNext = useCallback(() => {
    if (currentIndex < 0 || currentIndex >= entries.length - 1) return;
    onNavigate(rowKey(entries[currentIndex + 1]));
  }, [currentIndex, entries, onNavigate]);

  useEffect(() => {
    if (selectedKey === null) return;

    function handleKeyDown(e: KeyboardEvent) {
      const target = e.target as HTMLElement;
      if (target.closest && target.closest("[data-log-scrollable]")) return;

      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
        e.preventDefault();
        navigatePrev();
      }
      if (e.key === "ArrowRight" || e.key === "ArrowDown") {
        e.preventDefault();
        navigateNext();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [selectedKey, onClose, navigatePrev, navigateNext]);

  useEffect(() => {
    if (selectedKey === null) return;

    function handleMouseDown(e: MouseEvent) {
      const target = e.target as HTMLElement;
      if (drawerRef.current?.contains(target)) return;
      if (target.closest("tbody")) return;
      onClose();
    }

    document.addEventListener("mousedown", handleMouseDown);
    return () => document.removeEventListener("mousedown", handleMouseDown);
  }, [selectedKey, onClose]);

  if (selectedKey === null) return null;

  const useOverlay = isMobile || isTablet;

  return (
    <Drawer
      open={selectedKey !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      direction={isMobile ? "bottom" : "right"}
      modal={useOverlay}
    >
      {/* --z-drawer* tokens derive from --z-status-bar in global.css, so the
          drawer and its backdrop always stack above the sticky chrome. */}
      {useOverlay && <DrawerOverlay className="z-[var(--z-drawer-backdrop)] bg-[var(--overlay-background)]" />}
      <DrawerContentUnstyled
        ref={drawerRef}
        className={cn(
          "fixed z-[var(--z-drawer-layer)] flex flex-col overflow-hidden bg-card",
          isMobile
            ? "bottom-0 left-0 max-h-[70vh] w-full rounded-t-lg border-t border-border shadow-lg"
            : "right-2 top-2 bottom-2 w-[var(--size-drawer)] rounded-lg border border-border shadow-lg",
        )}
        id={DETAIL_DRAWER_ID}
        aria-label="Log entry detail"
        data-testid="log-detail-drawer"
        // This component owns closing (Escape via the document-level handler
        // above, outside-click via the tbody exclusion below) — the default
        // Radix/vaul dismissal behavior would close on ANY outside click,
        // including clicking a different log row, and would double-fire
        // Escape handling alongside the arrow-key navigation above.
        onEscapeKeyDown={(e) => e.preventDefault()}
        onInteractOutside={(e) => e.preventDefault()}
      >
        <DrawerTitle className="sr-only">Log entry detail</DrawerTitle>
        <div className="flex shrink-0 items-center justify-between border-b border-[var(--border-subtle)] px-3 py-2">
          <div className="flex gap-1">
            <button
              type="button"
              className="inline-flex size-[var(--size-icon-btn)] items-center justify-center rounded-sm border-none bg-transparent p-0 text-body text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:cursor-default disabled:text-foreground-faint disabled:hover:bg-transparent focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
              onClick={navigatePrev}
              disabled={currentIndex <= 0}
              aria-label="Previous entry"
            >
              ←
            </button>
            <button
              type="button"
              className="inline-flex size-[var(--size-icon-btn)] items-center justify-center rounded-sm border-none bg-transparent p-0 text-body text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:cursor-default disabled:text-foreground-faint disabled:hover:bg-transparent focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
              onClick={navigateNext}
              disabled={currentIndex >= entries.length - 1}
              aria-label="Next entry"
            >
              →
            </button>
          </div>
          <button
            type="button"
            className="inline-flex size-[var(--size-icon-btn)] items-center justify-center rounded-sm border-none bg-transparent p-0 text-body text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
            onClick={onClose}
            aria-label="Close detail panel"
          >
            ✕
          </button>
        </div>

        {isFilteredOut ? (
          <div className="px-4 py-6 text-center font-sans text-sm text-muted-foreground">
            <p>This entry is no longer visible with the current filters.</p>
            <button
              type="button"
              className="mt-3 cursor-pointer border-none bg-transparent text-sm text-foreground-secondary underline underline-offset-[var(--spacing-0-5)] hover:text-foreground"
              onClick={onClose}
            >
              Close
            </button>
          </div>
        ) : entry ? (
          <div className="flex-1 overflow-y-auto p-0">
            <div className={cn("flex items-center justify-between p-3", levelSurfaceClass(entry.level))}>
              <span
                className={cn("font-mono text-[length:var(--text-mono-md)] font-semibold", levelTextClass(entry.level))}
              >
                {entry.level}
              </span>
              <span className="font-mono text-[length:var(--text-mono-sm)] text-foreground-secondary">
                {formatTimestamp(entry.timestamp)}
              </span>
            </div>

            <div className="px-3 pb-3">
              <div className="mb-2 flex items-center justify-between">
                <span className="shrink-0 font-sans text-xs uppercase tracking-[var(--text-label-tracking-tight)] text-muted-foreground">
                  message
                </span>
                <CopyButton text={entry.message} label="Copy message" />
              </div>
              <pre
                className="m-0 max-h-[40%] overflow-y-auto whitespace-pre-wrap rounded-md bg-muted p-3 font-mono text-[length:var(--text-mono-sm)] leading-[var(--text-small-leading)] break-all [overflow-wrap:anywhere] text-foreground"
                data-log-scrollable
              >
                {entry.message}
              </pre>
            </div>

            {entry.exc_info && (
              <div className="px-3 pb-3">
                <div className="mb-2 flex items-center justify-between">
                  <span className="shrink-0 font-sans text-xs uppercase tracking-[var(--text-label-tracking-tight)] text-muted-foreground">
                    exception
                  </span>
                  <CopyButton text={entry.exc_info} label="Copy exception" />
                </div>
                <pre
                  className="m-0 max-h-[40%] overflow-y-auto whitespace-pre-wrap rounded-md border-l-[length:var(--border-thick)] border-destructive bg-muted p-3 font-mono text-[length:var(--text-mono-sm)] leading-[var(--text-small-leading)] break-all [overflow-wrap:anywhere] text-foreground"
                  data-log-scrollable
                >
                  {entry.exc_info}
                </pre>
              </div>
            )}

            <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 px-3 py-4 [&_dd]:m-0 [&_dd]:flex [&_dd]:items-center [&_dd]:gap-1 [&_dd]:overflow-hidden [&_dd]:text-sm [&_dd]:text-foreground [&_dt]:pt-px [&_dt]:text-right [&_dt]:font-sans [&_dt]:text-xs [&_dt]:uppercase [&_dt]:tracking-[var(--text-label-tracking-tight)] [&_dt]:text-muted-foreground">
              {entry.app_key && (
                <>
                  <dt>App</dt>
                  <dd>
                    <Link
                      href={appDetailPath(entry.app_key)}
                      className="text-primary underline decoration-[color:color-mix(in_srgb,var(--primary)_40%,transparent)] underline-offset-[var(--spacing-0-5)] hover:text-[var(--primary-hover)] hover:decoration-[var(--primary-hover)]"
                    >
                      {entry.app_key} ↗
                    </Link>
                  </dd>
                </>
              )}
              {entry.instance_name && (
                <>
                  <dt>Instance</dt>
                  <dd className="truncate font-mono text-[length:var(--text-mono-sm)]">{entry.instance_name}</dd>
                </>
              )}
              {entry.execution_id && (
                <>
                  <dt>Execution</dt>
                  <dd className="truncate font-mono text-[length:var(--text-mono-sm)]">
                    <ExecutionIdLink
                      entry={entry}
                      linkClassName="block min-w-0 truncate text-primary underline decoration-[color:color-mix(in_srgb,var(--primary)_40%,transparent)] underline-offset-[var(--spacing-0-5)] hover:text-[var(--primary-hover)] hover:decoration-[var(--primary-hover)]"
                      mutedClassName="block min-w-0 truncate text-foreground-faint"
                      title={entry.execution_id}
                    >
                      {entry.execution_id}
                    </ExecutionIdLink>
                    <CopyButton text={entry.execution_id} label="Copy execution ID" />
                  </dd>
                </>
              )}
              <dt>Function</dt>
              <dd className="truncate font-mono text-[length:var(--text-mono-sm)]">{entry.func_name}()</dd>
              <dt>Module</dt>
              <dd className="truncate font-mono text-[length:var(--text-mono-sm)]">
                {entry.logger_name.split(".").pop()}
              </dd>
              <dt>Line</dt>
              <dd className="truncate font-mono text-[length:var(--text-mono-sm)]">{entry.lineno}</dd>
              <dt>Logger</dt>
              <dd className="truncate font-mono text-[length:var(--text-mono-sm)]">{entry.logger_name}</dd>
            </dl>
          </div>
        ) : null}
      </DrawerContentUnstyled>
    </Drawer>
  );
}

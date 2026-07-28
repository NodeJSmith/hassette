import type { MouseEvent as ReactMouseEvent } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "wouter";

import type { LogEntry } from "@/api/endpoints";
import { Drawer, DrawerContentUnstyled, DrawerOverlay, DrawerTitle } from "@/components/ui/drawer";
import { BREAKPOINT_MOBILE, BREAKPOINT_TABLET, useMediaQuery } from "@/hooks/use-media-query";
import { cn } from "@/lib/utils";
import { appDetailPath } from "@/utils/app-routes";
import { formatTimestamp } from "@/utils/format";

import { COPY_CONFIRM_MS, DETAIL_DRAWER_ID, levelClass } from "./constants";
import { ExecutionIdLink } from "./execution-id-link";
import styles from "./log-detail-drawer.module.css";
import type { RowKey } from "./types";
import { rowKey } from "./types";

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
      className={styles.copyBtn}
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
      {useOverlay && <DrawerOverlay />}
      <DrawerContentUnstyled
        ref={drawerRef}
        className={cn(styles.drawer, isMobile ? styles.bottomSheet : styles.sidePanel)}
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
        <div className={styles.headerBar}>
          <div className={styles.navButtons}>
            <button
              type="button"
              className={styles.iconBtn}
              onClick={navigatePrev}
              disabled={currentIndex <= 0}
              aria-label="Previous entry"
            >
              ←
            </button>
            <button
              type="button"
              className={styles.iconBtn}
              onClick={navigateNext}
              disabled={currentIndex >= entries.length - 1}
              aria-label="Next entry"
            >
              →
            </button>
          </div>
          <button type="button" className={styles.iconBtn} onClick={onClose} aria-label="Close detail panel">
            ✕
          </button>
        </div>

        {isFilteredOut ? (
          <div className={styles.filteredOut}>
            <p>This entry is no longer visible with the current filters.</p>
            <button type="button" className={styles.clearFilterBtn} onClick={onClose}>
              Close
            </button>
          </div>
        ) : entry ? (
          <div className={styles.content}>
            <div className={cn(styles.severityRow, levelClass(styles, "level", entry.level))}>
              <span className={styles.levelLabel}>{entry.level}</span>
              <span className={styles.timestamp}>{formatTimestamp(entry.timestamp)}</span>
            </div>

            <div className={styles.section}>
              <div className={styles.sectionHeader}>
                <span className={styles.sectionLabel}>message</span>
                <CopyButton text={entry.message} label="Copy message" />
              </div>
              <pre className={styles.codeBlock} data-log-scrollable>
                {entry.message}
              </pre>
            </div>

            {entry.exc_info && (
              <div className={styles.section}>
                <div className={styles.sectionHeader}>
                  <span className={styles.sectionLabel}>exception</span>
                  <CopyButton text={entry.exc_info} label="Copy exception" />
                </div>
                <pre className={cn(styles.codeBlock, styles.exceptionBlock)} data-log-scrollable>
                  {entry.exc_info}
                </pre>
              </div>
            )}

            <dl className={styles.metaGrid}>
              {entry.app_key && (
                <>
                  <dt>App</dt>
                  <dd>
                    <Link href={appDetailPath(entry.app_key)} className={styles.appLink}>
                      {entry.app_key} ↗
                    </Link>
                  </dd>
                </>
              )}
              {entry.instance_name && (
                <>
                  <dt>Instance</dt>
                  <dd className={styles.monoValue}>{entry.instance_name}</dd>
                </>
              )}
              {entry.execution_id && (
                <>
                  <dt>Execution</dt>
                  <dd className={styles.monoValue}>
                    <ExecutionIdLink entry={entry} linkClassName={styles.execLink}>
                      {entry.execution_id}
                    </ExecutionIdLink>
                    <CopyButton text={entry.execution_id} label="Copy execution ID" />
                  </dd>
                </>
              )}
              <dt>Function</dt>
              <dd className={styles.monoValue}>{entry.func_name}()</dd>
              <dt>Module</dt>
              <dd className={styles.monoValue}>{entry.logger_name.split(".").pop()}</dd>
              <dt>Line</dt>
              <dd className={styles.monoValue}>{entry.lineno}</dd>
              <dt>Logger</dt>
              <dd className={styles.monoValue}>{entry.logger_name}</dd>
            </dl>
          </div>
        ) : null}
      </DrawerContentUnstyled>
    </Drawer>
  );
}

import clsx from "clsx";
import { useCallback, useEffect, useRef } from "preact/hooks";
import { Link } from "wouter";

import type { LogEntry } from "../../../api/endpoints";
import { BREAKPOINT_MOBILE, BREAKPOINT_TABLET, useMediaQuery } from "../../../hooks/use-media-query";
import { useSignal } from "../../../hooks/use-signal";
import { useSubscribe } from "../../../hooks/use-subscribe";
import { formatTimestamp } from "../../../utils/format";
import { COPY_CONFIRM_MS, levelClass } from "./constants";
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
  const copied = useSignal(false);
  useSubscribe(copied);

  const handleCopy = useCallback(
    async (e: MouseEvent) => {
      e.stopPropagation();
      try {
        await navigator.clipboard.writeText(text);
        copied.value = true;
        setTimeout(() => {
          copied.value = false;
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
      class={styles.copyBtn}
      onClick={handleCopy}
      aria-label={label}
      title={copied.value ? "Copied" : label}
    >
      {copied.value ? "✓" : "⧉"}
    </button>
  );
}

export function LogDetailDrawer({ selectedKey, entries, onClose, onNavigate }: Props) {
  const isMobile = useMediaQuery(BREAKPOINT_MOBILE);
  const isTablet = useMediaQuery(BREAKPOINT_TABLET);
  const drawerRef = useRef<HTMLElement>(null);

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
    <>
      {useOverlay && <div class={styles.backdrop} onClick={onClose} aria-hidden="true" />}
      <aside
        ref={drawerRef}
        class={clsx(styles.drawer, isMobile ? styles.bottomSheet : styles.sidePanel)}
        role="complementary"
        aria-label="Log entry detail"
        data-testid="log-detail-drawer"
      >
        {/* Header bar */}
        <div class={styles.headerBar}>
          <div class={styles.navButtons}>
            <button
              type="button"
              class={styles.iconBtn}
              onClick={navigatePrev}
              disabled={currentIndex <= 0}
              aria-label="Previous entry"
            >
              ←
            </button>
            <button
              type="button"
              class={styles.iconBtn}
              onClick={navigateNext}
              disabled={currentIndex >= entries.length - 1}
              aria-label="Next entry"
            >
              →
            </button>
          </div>
          <button type="button" class={styles.iconBtn} onClick={onClose} aria-label="Close detail panel">
            ✕
          </button>
        </div>

        {isFilteredOut ? (
          <div class={styles.filteredOut}>
            <p>This entry is no longer visible with the current filters.</p>
            <button type="button" class={styles.clearFilterBtn} onClick={onClose}>
              Close
            </button>
          </div>
        ) : entry ? (
          <div class={styles.content}>
            {/* Severity + timestamp */}
            <div class={clsx(styles.severityRow, levelClass(styles, "level", entry.level))}>
              <span class={styles.levelLabel}>{entry.level}</span>
              <span class={styles.timestamp}>{formatTimestamp(entry.timestamp)}</span>
            </div>

            {/* Metadata grid */}
            <dl class={styles.metaGrid}>
              {entry.app_key && (
                <>
                  <dt>App</dt>
                  <dd>
                    <Link href={`/apps/${entry.app_key}`} class={styles.appLink}>
                      {entry.app_key} ↗
                    </Link>
                  </dd>
                </>
              )}
              {entry.instance_name && (
                <>
                  <dt>Instance</dt>
                  <dd class={styles.monoValue}>{entry.instance_name}</dd>
                </>
              )}
              {entry.execution_id && (
                <>
                  <dt>Execution</dt>
                  <dd class={styles.monoValue}>
                    {entry.execution_id}
                    <CopyButton text={entry.execution_id} label="Copy execution ID" />
                  </dd>
                </>
              )}
              <dt>Function</dt>
              <dd class={styles.monoValue}>{entry.func_name}()</dd>
              <dt>Module</dt>
              <dd class={styles.monoValue}>{entry.logger_name.split(".").pop()}</dd>
              <dt>Line</dt>
              <dd class={styles.monoValue}>{entry.lineno}</dd>
              <dt>Logger</dt>
              <dd class={styles.monoValue}>{entry.logger_name}</dd>
            </dl>

            {/* Message section */}
            <div class={styles.section}>
              <div class={styles.sectionHeader}>
                <span class={styles.sectionLabel}>message</span>
                <CopyButton text={entry.message} label="Copy message" />
              </div>
              <pre class={styles.codeBlock} data-log-scrollable>
                {entry.message}
              </pre>
            </div>

            {/* Exception section */}
            {entry.exc_info && (
              <div class={styles.section}>
                <div class={styles.sectionHeader}>
                  <span class={styles.sectionLabel}>exception</span>
                  <CopyButton text={entry.exc_info} label="Copy exception" />
                </div>
                <pre class={clsx(styles.codeBlock, styles.exceptionBlock)} data-log-scrollable>
                  {entry.exc_info}
                </pre>
              </div>
            )}
          </div>
        ) : null}
      </aside>
    </>
  );
}

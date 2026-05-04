import { useEffect, useRef } from "preact/hooks";
import { signal } from "@preact/signals";
import { createHighlighter } from "shiki";
import { getAppSource } from "../../api/endpoints";
import type { AppSourceData, ListenerData } from "../../api/endpoints";
import { parseSourceLocation } from "../../utils/format";

interface Props {
  appKey: string;
  listeners: ListenerData[];
  focusLine?: number;
}

/**
 * Parse handler annotations from listeners.
 * Returns a map of line_number → handler_method name.
 * source_location format: "filename.py:LINE"
 */
function buildAnnotationMap(listeners: ListenerData[]): Map<number, string[]> {
  const map = new Map<number, string[]>();
  for (const l of listeners) {
    if (!l.source_location) continue;
    const { line } = parseSourceLocation(l.source_location);
    if (line === null) continue;
    const existing = map.get(line) ?? [];
    existing.push(l.handler_method);
    map.set(line, existing);
  }
  return map;
}

// Module-level Shiki highlighter cache (shared across component instances)
let highlighterPromise: ReturnType<typeof createHighlighter> | null = null;

function getHighlighter() {
  if (!highlighterPromise) {
    highlighterPromise = createHighlighter({
      langs: ["python"],
      themes: ["github-light", "github-dark"],
    }).catch((e) => {
      highlighterPromise = null;
      throw e;
    });
  }
  return highlighterPromise;
}

export function CodeTab({ appKey, listeners, focusLine }: Props) {
  const loading = useRef(signal(true)).current;
  const error = useRef(signal<string | null>(null)).current;
  const source = useRef(signal<AppSourceData | null>(null)).current;
  const highlightedHtml = useRef(signal<string | null>(null)).current;

  const annotationMap = buildAnnotationMap(listeners);

  useEffect(() => {
    let cancelled = false;
    loading.value = true;
    error.value = null;
    source.value = null;
    highlightedHtml.value = null;

    async function load() {
      try {
        const data = await getAppSource(appKey);
        if (cancelled) return;
        source.value = data;

        // Highlight code
        const hl = await getHighlighter();
        if (cancelled) return;

        const html = hl.codeToHtml(data.content, {
          lang: "python",
          themes: { light: "github-light", dark: "github-dark" },
          defaultColor: false,
        });
        if (cancelled) return;
        highlightedHtml.value = html;
      } catch (err) {
        if (cancelled) return;
        const msg = err instanceof Error ? err.message : String(err);
        if (msg.includes("404") || msg.toLowerCase().includes("not found")) {
          error.value = "Source file not found at expected path";
        } else {
          error.value = msg;
        }
      } finally {
        if (!cancelled) loading.value = false;
      }
    }

    void load();
    return () => { cancelled = true; };
  }, [appKey]);

  if (loading.value) {
    return (
      <div class="ht-code-tab__loading" data-testid="code-tab-loading">
        <span class="ht-text-muted ht-text-sm">Loading source…</span>
      </div>
    );
  }

  if (error.value) {
    return (
      <div class="ht-code-tab__error ht-card" data-testid="code-tab-error">
        <p class="ht-text-muted ht-text-sm">{error.value}</p>
      </div>
    );
  }

  useEffect(() => {
    if (!focusLine || loading.value) return;
    const el = document.querySelector(`[data-testid="code-line-${focusLine}"]`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      el.classList.add("ht-code-tab__gutter-line--focus");
    }
  }, [focusLine, loading.value]);

  if (!source.value) return null;

  const lines = source.value.content.replace(/\r\n/g, "\n").split("\n");
  // Remove trailing empty line from split if present
  const lineCount = lines[lines.length - 1] === "" ? lines.length - 1 : lines.length;

  const handleCopyPath = () => {
    if (source.value?.filename) {
      void navigator.clipboard.writeText(source.value.filename);
    }
  };

  return (
    <div class="ht-code-tab" data-testid="code-tab-content">
      <div class="ht-code-tab__header" data-testid="code-tab-header">
        <span class="ht-text-mono ht-text-sm ht-text-muted">{source.value.filename}</span>
        <div class="ht-code-tab__header-meta">
          <span class="ht-text-muted ht-text-sm">{lineCount} lines</span>
          <span class="ht-code-tab__readonly-label">read-only</span>
          <button
            type="button"
            class="ht-btn ht-btn--ghost ht-btn--sm"
            data-testid="copy-path-btn"
            onClick={handleCopyPath}
            aria-label="Copy file path"
          >
            copy path
          </button>
        </div>
      </div>
      <div class="ht-code-tab__body">
        {/* Gutter with line numbers and annotations */}
        <div class="ht-code-tab__gutter" aria-hidden="true">
          {Array.from({ length: lineCount }, (_, i) => {
            const lineNum = i + 1;
            const annotations = annotationMap.get(lineNum);
            return (
              <div
                key={lineNum}
                class={`ht-code-tab__gutter-line${annotations ? " ht-code-tab__gutter-line--annotated" : ""}`}
                data-testid={`code-line-${lineNum}`}
              >
                <span class="ht-code-tab__line-num">{lineNum}</span>
                {annotations && (
                  <span
                    class="ht-code-tab__annotation"
                    data-testid={`gutter-annotation-${lineNum}`}
                    title={annotations.join(", ")}
                  >
                    {annotations[0]}
                  </span>
                )}
              </div>
            );
          })}
        </div>

        {/* Highlighted source */}
        <div
          class="ht-code-tab__source"
          // biome-ignore lint/security/noDangerouslySetInnerHtml: Shiki output is trusted
          dangerouslySetInnerHTML={{ __html: highlightedHtml.value ?? "" }}
        />
      </div>
    </div>
  );
}

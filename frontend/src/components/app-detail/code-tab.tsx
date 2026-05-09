import { useEffect, useRef } from "preact/hooks";
import { signal } from "@preact/signals";
import { useQueryParams } from "../../hooks/use-query-params";
import type { HighlighterGeneric } from "shiki";
import { getAppSource } from "../../api/endpoints";
import type { AppSourceData, ListenerData } from "../../api/endpoints";
import { Spinner } from "../shared/spinner";
import { parseSourceLocation } from "../../utils/format";

interface Props {
  appKey: string;
  listeners: ListenerData[];
}

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

let highlighterPromise: Promise<HighlighterGeneric<never, never>> | null = null;

function getHighlighter() {
  if (!highlighterPromise) {
    highlighterPromise = import("shiki")
      .then(({ createHighlighter }) =>
        createHighlighter({
          langs: ["python"],
          themes: ["github-light", "github-dark"],
        }),
      )
      .catch((e) => {
        highlighterPromise = null;
        throw e;
      });
  }
  return highlighterPromise;
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// Depends on Shiki emitting exactly `<span class="line">` with no extra attributes.
// If this breaks after a Shiki upgrade, check codeToHtml output format.
function injectLineNumbers(html: string, annotationMap: Map<number, string[]>): string {
  let lineNum = 0;
  return html.replace(/<span class="line">/g, () => {
    lineNum++;
    const annotations = annotationMap.get(lineNum);
    const annotatedClass = annotations ? " line--annotated" : "";
    const safe = annotations?.map(escapeHtml);
    const titleAttr = safe ? ` title="${safe.join(", ")}"` : "";
    return `<span class="line${annotatedClass}" data-line="${lineNum}" data-testid="code-line-${lineNum}"${titleAttr}><span class="line-num">${lineNum}</span>`;
  });
}

export function CodeTab({ appKey, listeners }: Props) {
  const qp = useQueryParams();
  const lineParam = qp.get("line");
  const focusLine = lineParam ? parseInt(lineParam, 10) : undefined;
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

        const hl = await getHighlighter();
        if (cancelled) return;

        const rawHtml = hl.codeToHtml(data.content, {
          lang: "python",
          themes: { light: "github-light", dark: "github-dark" },
          defaultColor: false,
        });
        if (cancelled) return;
        highlightedHtml.value = rawHtml;
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

  useEffect(() => {
    if (!focusLine || loading.value) return;
    const prev = document.querySelector(".line--focus");
    prev?.classList.remove("line--focus");
    const el = document.querySelector(`[data-testid="code-line-${focusLine}"]`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      el.classList.add("line--focus");
    }
  }, [focusLine, loading.value]);

  if (loading.value) {
    return (
      <Spinner />
    );
  }

  if (error.value) {
    return (
      <div class="ht-code-tab__error ht-card" data-testid="code-tab-error">
        <p class="ht-text-muted ht-text-sm">{error.value}</p>
      </div>
    );
  }

  if (!source.value || !highlightedHtml.value) return null;

  const lines = source.value.content.replace(/\r\n/g, "\n").split("\n");
  const lineCount = lines[lines.length - 1] === "" ? lines.length - 1 : lines.length;

  const processedHtml = injectLineNumbers(highlightedHtml.value, annotationMap);

  const handleCopyPath = () => {
    if (source.value?.filename) {
      void navigator.clipboard.writeText(source.value.filename);
    }
  };

  return (
    <div class="ht-code-tab" data-testid="code-tab-content">
      <div class="ht-code-tab__header" data-testid="code-tab-header">
        <div class="ht-code-tab__header-source">
          <span class="ht-detail-label">Source</span>
          <span class="ht-text-mono ht-text-sm ht-text-muted">{source.value.filename}</span>
        </div>
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
      <div
        class="ht-code-tab__body"
        // biome-ignore lint/security/noDangerouslySetInnerHtml: Shiki output is trusted
        dangerouslySetInnerHTML={{ __html: processedHtml }}
      />
    </div>
  );
}

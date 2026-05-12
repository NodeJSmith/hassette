import { useEffect } from "preact/hooks";
import { useSignal } from "../../hooks/use-signal";
import { useQueryParams } from "../../hooks/use-query-params";
import type { HighlighterGeneric } from "shiki";
import { getAppSource } from "../../api/endpoints";
import type { AppSourceData, ListenerData } from "../../api/endpoints";
import { Spinner } from "../shared/spinner";
import { parseSourceLocation } from "../../utils/format";
import { Button } from "../shared/button";
import { Card } from "../shared/card";
import styles from "./code-tab.module.css";

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

const SHIKI_LINE_RE = /<span class="line">/g;

function injectLineNumbers(html: string, annotationMap: Map<number, string[]>): string {
  if (!SHIKI_LINE_RE.test(html)) return html;
  SHIKI_LINE_RE.lastIndex = 0;

  let lineNum = 0;
  return html.replace(SHIKI_LINE_RE, () => {
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
  const loading = useSignal(true);
  const error = useSignal<string | null>(null);
  const source = useSignal<AppSourceData | null>(null);
  const highlightedHtml = useSignal<string | null>(null);

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
      <Card data-testid="code-tab-error">
        <p class="ht-text-muted ht-text-sm">{error.value}</p>
      </Card>
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
    <div class={styles.codeTab} data-testid="code-tab-content">
      <div class={styles.header} data-testid="code-tab-header">
        <div class={styles.headerSource}>
          <span class="ht-detail-label">Source</span>
          <span class="ht-text-mono ht-text-sm ht-text-muted">{source.value.filename}</span>
        </div>
        <div class={styles.headerMeta}>
          <span class="ht-text-muted ht-text-sm">{lineCount} lines</span>
          <span class={styles.readonlyLabel}>read-only</span>
          <Button
            ghost
            size="sm"
            data-testid="copy-path-btn"
            onClick={handleCopyPath}
            aria-label="Copy file path"
          >
            copy path
          </Button>
        </div>
      </div>
      <div
        class={styles.body}
        // biome-ignore lint/security/noDangerouslySetInnerHtml: Shiki output is trusted
        dangerouslySetInnerHTML={{ __html: processedHtml }}
      />
    </div>
  );
}

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

import type { AppSourceData, ListenerData } from "../../api/endpoints";
import { getAppSource } from "../../api/endpoints";
import { useQueryParams } from "../../hooks/use-query-params";
import { parseSourceLocation } from "../../utils/format";
import { getShikiHighlighter, SHIKI_THEMES } from "../../utils/shiki";
import { Spinner } from "../shared/spinner";

interface Props {
  appKey: string;
  listeners: ListenerData[];
}

function buildAnnotationMap(listeners: ListenerData[]): Map<number, string[]> {
  const map = new Map<number, string[]>();
  for (const listener of listeners) {
    if (!listener.source_location) continue;
    const { line } = parseSourceLocation(listener.source_location);
    if (line === null) continue;
    const existing = map.get(line) ?? [];
    existing.push(listener.handler_method);
    map.set(line, existing);
  }
  return map;
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

const SHIKI_LINE_RE = /<span class="line">/g;
const DETAIL_LABEL_CLASS = "text-xs font-medium uppercase tracking-[var(--text-label-tracking)] text-muted-foreground";

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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [source, setSource] = useState<AppSourceData | null>(null);
  const [highlightedHtml, setHighlightedHtml] = useState<string | null>(null);

  const annotationMap = buildAnnotationMap(listeners);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setSource(null);
    setHighlightedHtml(null);

    async function load() {
      try {
        const data = await getAppSource(appKey, controller.signal);
        if (controller.signal.aborted) return;
        setSource(data);

        const hl = await getShikiHighlighter("python");
        if (controller.signal.aborted) return;

        const rawHtml = hl.codeToHtml(data.content, {
          lang: "python",
          themes: SHIKI_THEMES,
          defaultColor: false,
        });
        if (controller.signal.aborted) return;
        setHighlightedHtml(rawHtml);
      } catch (err) {
        if (controller.signal.aborted) return;
        const msg = err instanceof Error ? err.message : String(err);
        if (msg.includes("404") || msg.toLowerCase().includes("not found")) {
          setError("Source file not found at expected path");
        } else {
          setError(msg);
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }

    void load();
    return () => {
      controller.abort();
    };
  }, [appKey]);

  useEffect(() => {
    if (!focusLine || loading) return;
    const prev = document.querySelector(".line--focus");
    prev?.classList.remove("line--focus");
    const el = document.querySelector(`[data-testid="code-line-${focusLine}"]`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      el.classList.add("line--focus");
    }
  }, [focusLine, loading]);

  if (loading) {
    return <Spinner />;
  }

  if (error) {
    return (
      <Card data-testid="code-tab-error">
        <p className="text-sm text-muted-foreground">{error}</p>
      </Card>
    );
  }

  if (!source || !highlightedHtml) return null;

  const lines = source.content.replace(/\r\n/g, "\n").split("\n");
  const lineCount = lines[lines.length - 1] === "" ? lines.length - 1 : lines.length;

  const processedHtml = injectLineNumbers(highlightedHtml, annotationMap);

  const handleCopyPath = () => {
    if (source?.filename) {
      void navigator.clipboard.writeText(source.filename);
    }
  };

  return (
    <div className="overflow-hidden rounded-md border border-border bg-card" data-testid="code-tab-content">
      <div
        className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-muted px-4 py-2"
        data-testid="code-tab-header"
      >
        <div className="flex items-baseline gap-2">
          <span className={DETAIL_LABEL_CLASS}>Source</span>
          <span className="font-mono text-sm text-muted-foreground">{source.filename}</span>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <span className="text-sm text-muted-foreground">{lineCount} lines</span>
          <span className="rounded-sm border border-border px-2 py-px font-mono text-xs text-foreground-faint">
            read-only
          </span>
          <Button
            variant="ghost"
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
        className={cn(
          "max-h-[calc(100vh-280px)] overflow-auto [-webkit-overflow-scrolling:touch]",
          "[&_.shiki]:m-0 [&_.shiki]:rounded-none [&_.shiki]:!bg-[var(--bg-page)] [&_.shiki]:px-0 [&_.shiki]:py-3",
          "[&_.shiki]:text-sm [&_.shiki]:leading-relaxed [&_.shiki_code]:block [&_.shiki_code]:bg-transparent [&_.shiki_code]:p-0",
          "[&_.shiki_span:not(.line):not(.line-num)]:text-[var(--shiki-light,var(--ink-1))]",
          "dark:[&_.shiki_span:not(.line):not(.line-num)]:text-[var(--shiki-dark,var(--ink-1))]",
          "[&_.line]:inline-flex [&_.line]:min-w-full [&_.line]:pr-4",
          "[&_.line--annotated]:cursor-help [&_.line--annotated]:bg-[var(--code-annotate-bg)]",
          "[&_.line--focus]:bg-[var(--code-focus-bg)]",
          "[&_.line-num]:mr-3 [&_.line-num]:min-w-[3ch] [&_.line-num]:shrink-0 [&_.line-num]:select-none",
          "[&_.line-num]:border-r [&_.line-num]:border-border [&_.line-num]:px-3 [&_.line-num]:text-right",
          "[&_.line-num]:text-foreground-faint",
        )}
        // Shiki-generated HTML from our own source fetch, not user input — safe to inject.
        dangerouslySetInnerHTML={{ __html: processedHtml }}
      />
    </div>
  );
}

import { useEffect, useState } from "react";

import type { AppSourceData, ListenerData } from "../../api/endpoints";
import { getAppSource } from "../../api/endpoints";
import { useQueryParams } from "../../hooks/use-query-params";
import { parseSourceLocation } from "../../utils/format";
import { getShikiHighlighter, SHIKI_THEMES } from "../../utils/shiki";
import { Button } from "../shared/button";
import { Card } from "../shared/card";
import { Spinner } from "../shared/spinner";
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
        <p className="ht-text-muted ht-text-sm">{error}</p>
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
    <div className={styles.codeTab} data-testid="code-tab-content">
      <div className={styles.header} data-testid="code-tab-header">
        <div className={styles.headerSource}>
          <span className="ht-detail-label">Source</span>
          <span className="ht-text-mono ht-text-sm ht-text-muted">{source.filename}</span>
        </div>
        <div className={styles.headerMeta}>
          <span className="ht-text-muted ht-text-sm">{lineCount} lines</span>
          <span className={styles.readonlyLabel}>read-only</span>
          <Button ghost size="sm" data-testid="copy-path-btn" onClick={handleCopyPath} aria-label="Copy file path">
            copy path
          </Button>
        </div>
      </div>
      <div
        className={styles.body}
        // Shiki-generated HTML from our own source fetch, not user input — safe to inject.
        dangerouslySetInnerHTML={{ __html: processedHtml }}
      />
    </div>
  );
}

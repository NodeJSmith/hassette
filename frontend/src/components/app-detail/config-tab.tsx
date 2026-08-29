import { useEffect, useState } from "react";

import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

import type { ConfigRecord, SchemaNode } from "../../api/config-view-types";
import type { AppConfigData } from "../../api/endpoints";
import { getAppConfig } from "../../api/endpoints";
import { getShikiHighlighter, SHIKI_THEMES } from "../../utils/shiki";
import { ConfigSchemaView, ExpandableValue } from "../shared/config-schema-view";
import { EmptyState } from "../shared/empty-state";
import { Spinner } from "../shared/spinner";
import { SECTION_LABEL_CLASS } from "./overview-section";

interface Props {
  appKey: string;
}

const DATA_TABLE_CLASS =
  "w-full border-collapse bg-card [&_thead_tr]:bg-muted [&_th]:border-b [&_th]:border-border [&_th]:px-3 [&_th]:py-2 [&_th]:text-left [&_th]:font-mono [&_th]:text-xs [&_th]:font-medium [&_th]:uppercase [&_th]:tracking-[var(--text-label-tracking)] [&_th]:text-muted-foreground [&_th]:whitespace-nowrap [&_td]:border-b [&_td]:border-border [&_td]:px-3 [&_td]:py-2 [&_td]:align-top [&_td]:text-[length:var(--text-small)] [&_tbody_tr:last-child_td]:border-b-0 [&_tbody_tr:hover]:bg-muted";

/** True when the value is a plain (non-array) object usable as a ConfigRecord. */
function isConfigRecord(value: unknown): value is ConfigRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function ConfigValue({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <>—</>;
  if (typeof value === "object") return <ExpandableValue value={value} />;
  return <>{String(value)}</>;
}

function SimpleConfigTable({ config }: { config: ConfigRecord }) {
  const entries = Object.entries(config);
  if (entries.length === 0) {
    return <EmptyState title="no configuration values" />;
  }

  return (
    <table className={cn(DATA_TABLE_CLASS, "table-auto [&_td_code]:break-all")} data-testid="config-values-table">
      <thead>
        <tr>
          <th className="w-[30%] whitespace-nowrap" scope="col">
            Key
          </th>
          <th className="w-[55%]" scope="col">
            Value
          </th>
        </tr>
      </thead>
      <tbody>
        {entries.map(([key, value]) => (
          <tr key={key}>
            <td>
              <code className="font-mono text-sm">{key}</code>
            </td>
            <td data-testid={`config-value-${key}`}>
              <code className="font-mono text-sm">
                <ConfigValue value={value} />
              </code>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function AppConfigContent({
  appConfig,
  schema,
  manifestValues,
  frameworkFields,
}: {
  appConfig: ConfigRecord;
  schema: SchemaNode | undefined;
  manifestValues?: ConfigRecord;
  frameworkFields?: string[];
}) {
  const displayValues = manifestValues ? { ...appConfig, ...manifestValues } : appConfig;
  if (schema) {
    return (
      <ConfigSchemaView
        schema={schema}
        values={displayValues}
        emptyMessage="no configuration fields"
        frameworkFields={frameworkFields}
      />
    );
  }
  return (
    <Card variant="config">
      <SimpleConfigTable config={displayValues} />
    </Card>
  );
}

export function ConfigTab({ appKey }: Props) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [configData, setConfigData] = useState<AppConfigData | null>(null);
  const [tomlHtml, setTomlHtml] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setConfigData(null);
    setTomlHtml(null);

    async function load() {
      try {
        const data = await getAppConfig(appKey, controller.signal);
        if (controller.signal.aborted) return;
        setConfigData(data);

        try {
          const hl = await getShikiHighlighter("toml");
          if (controller.signal.aborted) return;
          setTomlHtml(
            hl.codeToHtml(data.config_toml, {
              lang: "toml",
              themes: SHIKI_THEMES,
              defaultColor: false,
            }),
          );
        } catch {
          // Highlighting is best-effort — the plain-text fallback renders config_toml as-is.
        }
      } catch (err) {
        if (controller.signal.aborted) return;
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }

    void load();
    return () => {
      controller.abort();
    };
  }, [appKey]);

  if (loading) {
    return <Spinner />;
  }

  if (error) {
    return (
      <Card data-testid="config-tab-error">
        <p className="text-sm text-muted-foreground">{error}</p>
      </Card>
    );
  }

  if (!configData) return null;

  const appConfig = configData.app_config;
  const schema = configData.config_schema ?? undefined;
  const isListConfig = Array.isArray(appConfig);
  const manifestValues: ConfigRecord = { enabled: configData.enabled, autostart: configData.autostart };
  const frameworkFields = configData.framework_fields;

  return (
    <div className="pb-4" data-testid="config-tab-content">
      <div className="grid grid-cols-[1.4fr_1fr] gap-4 max-mobile:grid-cols-1">
        <div className="min-w-0 px-4 pb-4">
          {isListConfig ? (
            <div className="flex flex-col gap-6">
              {/* isListConfig is a stored boolean, so TS can't use it to narrow
                  appConfig here — hence the cast despite the guard above. */}
              {(appConfig as unknown[]).map((instanceCfg, idx) => (
                <div key={idx} className="min-w-0" data-testid={`config-instance-${idx}`}>
                  <h4 className="mb-3 border-b border-strong pb-2 font-sans text-sm font-semibold uppercase tracking-[var(--text-label-tracking-mid)] text-foreground-secondary">
                    Instance {idx}
                  </h4>
                  {isConfigRecord(instanceCfg) ? (
                    <AppConfigContent
                      appConfig={instanceCfg}
                      schema={schema}
                      manifestValues={manifestValues}
                      frameworkFields={frameworkFields}
                    />
                  ) : (
                    <p className="text-sm text-muted-foreground">{String(instanceCfg)}</p>
                  )}
                </div>
              ))}
            </div>
          ) : isConfigRecord(appConfig) ? (
            <AppConfigContent
              appConfig={appConfig}
              schema={schema}
              manifestValues={manifestValues}
              frameworkFields={frameworkFields}
            />
          ) : (
            <EmptyState title="no configuration values" />
          )}
        </div>

        <div className="min-w-0 px-4 pb-4">
          <h3 className={SECTION_LABEL_CLASS}>raw config</h3>
          <Card variant="config">
            <span className="font-mono text-xs text-muted-foreground">hassette.toml → apps.{appKey}.config</span>
            {tomlHtml ? (
              <div
                className={cn(
                  "mt-2 overflow-x-auto whitespace-pre rounded-sm border border-dashed border-border bg-muted p-3",
                  "font-mono text-xs [&_.shiki]:m-0 [&_.shiki]:bg-transparent [&_.shiki]:p-0",
                  "[&_.shiki]:font-inherit [&_.shiki]:text-inherit",
                  "[&_.shiki_span:not(.line)]:text-[var(--shiki-light,var(--ink-1))]",
                  "dark:[&_.shiki_span:not(.line)]:text-[var(--shiki-dark,var(--ink-1))]",
                )}
                data-testid="raw-config-toml"
                dangerouslySetInnerHTML={{ __html: tomlHtml }}
              />
            ) : (
              <pre
                className="mt-2 overflow-x-auto whitespace-pre rounded-sm border border-dashed border-border bg-muted p-3 font-mono text-xs"
                data-testid="raw-config-toml"
              >
                {configData.config_toml}
              </pre>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

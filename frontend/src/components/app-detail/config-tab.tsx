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
import styles from "./config-tab.module.css";

interface Props {
  appKey: string;
}

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
    <table className={cn("ht-table", styles.table)} data-testid="config-values-table">
      <thead>
        <tr>
          <th className={styles.colKey} scope="col">
            Key
          </th>
          <th className={styles.colValue} scope="col">
            Value
          </th>
        </tr>
      </thead>
      <tbody>
        {entries.map(([key, val]) => (
          <tr key={key}>
            <td>
              <code className="ht-text-mono ht-text-sm">{key}</code>
            </td>
            <td className={styles.value} data-testid={`config-value-${key}`}>
              <code className="ht-text-mono ht-text-sm">
                <ConfigValue value={val} />
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
        <p className="ht-text-muted ht-text-sm">{error}</p>
      </Card>
    );
  }

  if (!configData) return null;

  const cfg = configData;
  const appConfig = cfg.app_config;
  const schema = cfg.config_schema ?? undefined;
  const isListConfig = Array.isArray(appConfig);
  const manifestValues: ConfigRecord = { enabled: cfg.enabled, autostart: cfg.autostart };
  const frameworkFields = cfg.framework_fields;

  return (
    <div className={styles.configTab} data-testid="config-tab-content">
      <div className={styles.layout}>
        <div className={styles.fieldsCard}>
          {isListConfig ? (
            <div className={styles.instances}>
              {/* isListConfig is a stored boolean, so TS can't use it to narrow
                  appConfig here — hence the cast despite the guard above. */}
              {(appConfig as unknown[]).map((instanceCfg, idx) => (
                <div key={idx} className={styles.instanceBlock} data-testid={`config-instance-${idx}`}>
                  <h4 className={styles.instanceHeading}>Instance {idx}</h4>
                  {isConfigRecord(instanceCfg) ? (
                    <AppConfigContent
                      appConfig={instanceCfg}
                      schema={schema}
                      manifestValues={manifestValues}
                      frameworkFields={frameworkFields}
                    />
                  ) : (
                    <p className="ht-text-muted ht-text-sm">{String(instanceCfg)}</p>
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

        <div className={styles.rawCard}>
          <h3 className="ht-section-label">raw config</h3>
          <Card variant="config">
            <span className="ht-text-mono ht-text-xs ht-text-muted">hassette.toml → apps.{appKey}.config</span>
            {tomlHtml ? (
              <div
                className={styles.rawCode}
                data-testid="raw-config-toml"
                dangerouslySetInnerHTML={{ __html: tomlHtml }}
              />
            ) : (
              <pre className={styles.rawCode} data-testid="raw-config-toml">
                {cfg.config_toml}
              </pre>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

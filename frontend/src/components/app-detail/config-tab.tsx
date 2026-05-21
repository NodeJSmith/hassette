import clsx from "clsx";
import { useEffect, useState } from "preact/hooks";

import type { AppConfigData } from "../../api/endpoints";
import { getAppConfig } from "../../api/endpoints";
import { useSignal } from "../../hooks/use-signal";
import { Badge } from "../shared/badge";
import { Card } from "../shared/card";
import { EmptyState } from "../shared/empty-state";
import { Spinner } from "../shared/spinner";
import styles from "./config-tab.module.css";

interface Props {
  appKey: string;
}

type ConfigRecord = Record<string, unknown>;
type SchemaProperty = {
  type?: string;
  default?: unknown;
  description?: string;
  title?: string;
  anyOf?: { type?: string }[];
};
type ConfigSchema = {
  properties?: Record<string, SchemaProperty>;
  required?: string[];
};

function formatConfigValue(val: unknown): string {
  if (val === null || val === undefined) return "—";
  if (Array.isArray(val)) return `[${val.length} items]`;
  if (typeof val === "object") return `{${Object.keys(val as Record<string, unknown>).length} keys}`;
  return String(val);
}

function ConfigValue({ val }: { val: unknown }) {
  const [expanded, setExpanded] = useState(false);
  const isComplex = val !== null && typeof val === "object";

  if (!isComplex) return <>{formatConfigValue(val)}</>;

  return (
    <span>
      <button
        type="button"
        class={styles.configTableExpandBtn}
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
      >
        <svg class={styles.configTableExpandIcon} viewBox="0 0 12 12" width="10" height="10" aria-hidden="true">
          <polyline
            points={expanded ? "2,4 6,8 10,4" : "4,2 8,6 4,10"}
            fill="none"
            stroke="currentColor"
            stroke-width="1.5"
          />
        </svg>
        {formatConfigValue(val)}
      </button>
      {expanded && <pre class={styles.configTableExpandedValue}>{JSON.stringify(val, null, 2)}</pre>}
    </span>
  );
}

function resolveType(prop: SchemaProperty): string {
  if (prop.type) return prop.type;
  if (prop.anyOf) {
    const types = prop.anyOf.map((t) => t.type).filter(Boolean);
    return types.join(" | ") || "any";
  }
  return "any";
}

function SchemaConfigTable({ config, schema }: { config: ConfigRecord; schema: ConfigSchema }) {
  const properties = schema.properties ?? {};
  const propKeys = Object.keys(properties);
  const extraKeys = Object.keys(config).filter((k) => !propKeys.includes(k));
  const allKeys = [...propKeys, ...extraKeys];

  if (allKeys.length === 0) {
    return (
      <EmptyState title="no configuration fields" body="this app uses the default AppConfig with no custom fields." />
    );
  }

  return (
    <table class={clsx("ht-table ht-table--compact", styles.configTable)} data-testid="config-values-table">
      <thead>
        <tr>
          <th class={styles.configTableKey} scope="col">
            Key
          </th>
          <th class={styles.configTableColType} scope="col">
            Type
          </th>
          <th class={styles.configTableColValue} scope="col">
            Value
          </th>
        </tr>
      </thead>
      <tbody>
        {allKeys.map((key) => {
          const prop = properties[key];
          const value = config[key];
          const hasValue = value !== null && value !== undefined;
          const typeName = prop ? resolveType(prop) : typeof value;

          return (
            <tr key={key} data-testid={`config-value-${key}`}>
              <td class={styles.configTableKey}>{key}</td>
              <td class={styles.configTableColType}>
                <span class="ht-text-muted ht-text-xs">{typeName}</span>
              </td>
              <td class={clsx(styles.configTableValue, !hasValue && styles.configTableValueEmpty)}>
                <ConfigValue val={value} />
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function SimpleConfigTable({ config }: { config: ConfigRecord }) {
  const entries = Object.entries(config);
  if (entries.length === 0) {
    return <EmptyState title="no configuration values" />;
  }

  return (
    <table class={clsx("ht-table", styles.table)} data-testid="config-values-table">
      <thead>
        <tr>
          <th class={styles.colKey} scope="col">
            Key
          </th>
          <th class={styles.colValue} scope="col">
            Value
          </th>
        </tr>
      </thead>
      <tbody>
        {entries.map(([key, val]) => (
          <tr key={key}>
            <td>
              <code class="ht-text-mono ht-text-sm">{key}</code>
            </td>
            <td class={styles.value} data-testid={`config-value-${key}`}>
              <code class="ht-text-mono ht-text-sm">
                <ConfigValue val={val} />
              </code>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function ConfigTab({ appKey }: Props) {
  const loading = useSignal(true);
  const error = useSignal<string | null>(null);
  const configData = useSignal<AppConfigData | null>(null);

  useEffect(() => {
    let cancelled = false;
    loading.value = true;
    error.value = null;
    configData.value = null;

    async function load() {
      try {
        const data = await getAppConfig(appKey);
        if (cancelled) return;
        configData.value = data as AppConfigData;
      } catch (err) {
        if (cancelled) return;
        error.value = err instanceof Error ? err.message : String(err);
      } finally {
        if (!cancelled) loading.value = false;
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [appKey]);

  if (loading.value) {
    return <Spinner />;
  }

  if (error.value) {
    return (
      <Card data-testid="config-tab-error">
        <p class="ht-text-muted ht-text-sm">{error.value}</p>
      </Card>
    );
  }

  if (!configData.value) return null;

  const cfg = configData.value;
  const appConfig = cfg.app_config;
  const schema = (cfg as { config_schema?: ConfigSchema }).config_schema;
  const isListConfig = Array.isArray(appConfig);

  return (
    <div class={styles.configTab} data-testid="config-tab-content">
      {/* Metadata header */}
      <div class={styles.meta} data-testid="config-meta">
        <div class={styles.metaRow}>
          <span class="ht-detail-label">File</span>
          <code class="ht-text-mono ht-text-sm">{cfg.filename}</code>
        </div>
        <div class={styles.metaRow}>
          <span class="ht-detail-label">Class</span>
          <code class="ht-text-mono ht-text-sm">{cfg.class_name}</code>
        </div>
        <div class={styles.metaRow}>
          <span class="ht-detail-label">Enabled</span>
          <Badge variant={cfg.enabled ? "success" : "neutral"}>{cfg.enabled ? "yes" : "no"}</Badge>
        </div>
      </div>

      {/* 2-column layout: config table + raw values */}
      <div class={styles.layout}>
        <div class={styles.fieldsCard}>
          <h3 class="ht-section-label">configuration</h3>
          <Card variant="config">
            {isListConfig ? (
              <div class={styles.instances}>
                {(appConfig as unknown[]).map((instanceCfg, idx) => (
                  <div key={idx} class={styles.instanceBlock} data-testid={`config-instance-${idx}`}>
                    <h4 class={styles.instanceHeading}>Instance {idx}</h4>
                    {instanceCfg && typeof instanceCfg === "object" && !Array.isArray(instanceCfg) ? (
                      schema ? (
                        <SchemaConfigTable config={instanceCfg as ConfigRecord} schema={schema} />
                      ) : (
                        <SimpleConfigTable config={instanceCfg as ConfigRecord} />
                      )
                    ) : (
                      <p class="ht-text-muted ht-text-sm">{String(instanceCfg)}</p>
                    )}
                  </div>
                ))}
              </div>
            ) : appConfig && typeof appConfig === "object" && !Array.isArray(appConfig) ? (
              schema ? (
                <SchemaConfigTable config={appConfig as ConfigRecord} schema={schema} />
              ) : (
                <SimpleConfigTable config={appConfig as ConfigRecord} />
              )
            ) : (
              <EmptyState title="no configuration values" />
            )}
          </Card>
        </div>

        {/* Raw config card */}
        <div class={styles.rawCard}>
          <h3 class="ht-section-label">raw config</h3>
          <Card variant="config">
            <span class="ht-text-mono ht-text-xs ht-text-muted">hassette.toml → apps.{appKey}.config</span>
            <pre class={styles.rawCode}>{JSON.stringify(appConfig, null, 2)}</pre>
          </Card>
        </div>
      </div>
    </div>
  );
}

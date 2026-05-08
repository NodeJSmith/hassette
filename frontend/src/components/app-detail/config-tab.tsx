import { useEffect, useRef } from "preact/hooks";
import { signal } from "@preact/signals";
import { getAppConfig } from "../../api/endpoints";
import { Spinner } from "../shared/spinner";
import type { AppConfigData } from "../../api/endpoints";

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
  if (typeof val === "object") return JSON.stringify(val);
  return String(val);
}

function resolveType(prop: SchemaProperty): string {
  if (prop.type) return prop.type;
  if (prop.anyOf) {
    const types = prop.anyOf.map((t) => t.type).filter(Boolean);
    return types.join(" | ") || "any";
  }
  return "any";
}

function SchemaConfigTable({
  config,
  schema,
}: {
  config: ConfigRecord;
  schema: ConfigSchema;
}) {
  const properties = schema.properties ?? {};
  const propKeys = Object.keys(properties);
  const extraKeys = Object.keys(config).filter((k) => !propKeys.includes(k));
  const allKeys = [...propKeys, ...extraKeys];

  if (allKeys.length === 0) {
    return (
      <div class="ht-empty">
        <div class="ht-empty__icon">∅</div>
        <div class="ht-empty__title">no configuration fields</div>
        <div class="ht-empty__body">this app uses the default AppConfig with no custom fields.</div>
      </div>
    );
  }

  return (
    <table class="ht-table ht-table--compact ht-config-table" data-testid="config-values-table">
      <thead>
        <tr>
          <th class="ht-config-table__key" scope="col">Key</th>
          <th class="ht-config-table__col-type" scope="col">Type</th>
          <th class="ht-config-table__col-value" scope="col">Value</th>
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
              <td class="ht-config-table__key">{key}</td>
              <td class="ht-config-table__col-type">
                <span class="ht-text-muted ht-text-xs">{typeName}</span>
              </td>
              <td class={`ht-config-table__value${!hasValue ? " ht-config-table__value--empty" : ""}`}>
                {formatConfigValue(value)}
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
    return (
      <div class="ht-empty">
        <div class="ht-empty__icon">∅</div>
        <div class="ht-empty__title">no configuration values</div>
      </div>
    );
  }

  return (
    <table class="ht-table ht-config-tab__table" data-testid="config-values-table">
      <thead>
        <tr>
          <th class="ht-config-tab__col-key" scope="col">Key</th>
          <th class="ht-config-tab__col-value" scope="col">Value</th>
        </tr>
      </thead>
      <tbody>
        {entries.map(([key, val]) => (
          <tr key={key}>
            <td><code class="ht-text-mono ht-text-sm">{key}</code></td>
            <td class="ht-config-tab__value" data-testid={`config-value-${key}`}>
              <code class="ht-text-mono ht-text-sm">{formatConfigValue(val)}</code>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function ConfigTab({ appKey }: Props) {
  const loading = useRef(signal(true)).current;
  const error = useRef(signal<string | null>(null)).current;
  const configData = useRef(signal<AppConfigData | null>(null)).current;

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
    return () => { cancelled = true; };
  }, [appKey]);

  if (loading.value) {
    return (
      <Spinner />
    );
  }

  if (error.value) {
    return (
      <div class="ht-card" data-testid="config-tab-error">
        <p class="ht-text-muted ht-text-sm">{error.value}</p>
      </div>
    );
  }

  if (!configData.value) return null;

  const cfg = configData.value;
  const appConfig = cfg.app_config;
  const schema = (cfg as { config_schema?: ConfigSchema }).config_schema;
  const isListConfig = Array.isArray(appConfig);

  return (
    <div class="ht-config-tab" data-testid="config-tab-content">
      {/* Metadata header */}
      <div class="ht-config-tab__meta" data-testid="config-meta">
        <div class="ht-config-tab__meta-row">
          <span class="ht-detail-label">File</span>
          <code class="ht-text-mono ht-text-sm">{cfg.filename}</code>
        </div>
        <div class="ht-config-tab__meta-row">
          <span class="ht-detail-label">Class</span>
          <code class="ht-text-mono ht-text-sm">{cfg.class_name}</code>
        </div>
        <div class="ht-config-tab__meta-row">
          <span class="ht-detail-label">Enabled</span>
          <span class={`ht-badge ${cfg.enabled ? "ht-badge--success" : "ht-badge--neutral"}`}>
            {cfg.enabled ? "yes" : "no"}
          </span>
        </div>
      </div>

      {/* 2-column layout: config table + raw values */}
      <div class="ht-config-tab__layout">
        <div class="ht-config-tab__fields-card">
          <h3 class="ht-config-group__label">configuration</h3>
          <div class="ht-card ht-card--config">
          {isListConfig ? (
            <div class="ht-config-tab__instances">
              {(appConfig as unknown[]).map((instanceCfg, idx) => (
                <div key={idx} class="ht-config-tab__instance-block" data-testid={`config-instance-${idx}`}>
                  <h4 class="ht-config-tab__instance-heading">Instance {idx}</h4>
                  {instanceCfg && typeof instanceCfg === "object" && !Array.isArray(instanceCfg) ? (
                    schema
                      ? <SchemaConfigTable config={instanceCfg as ConfigRecord} schema={schema} />
                      : <SimpleConfigTable config={instanceCfg as ConfigRecord} />
                  ) : (
                    <p class="ht-text-muted ht-text-sm">{String(instanceCfg)}</p>
                  )}
                </div>
              ))}
            </div>
          ) : appConfig && typeof appConfig === "object" && !Array.isArray(appConfig) ? (
            schema
              ? <SchemaConfigTable config={appConfig as ConfigRecord} schema={schema} />
              : <SimpleConfigTable config={appConfig as ConfigRecord} />
          ) : (
            <div class="ht-empty">
              <div class="ht-empty__icon">∅</div>
              <div class="ht-empty__title">no configuration values</div>
            </div>
          )}
          </div>
        </div>

        {/* Raw config card */}
        <div class="ht-config-tab__raw-card">
          <h3 class="ht-config-group__label">raw config</h3>
          <div class="ht-card ht-card--config">
          <span class="ht-text-mono ht-text-xs ht-text-muted">hassette.toml → apps.{appKey}.config</span>
          <pre class="ht-config-tab__raw-code">{JSON.stringify(appConfig, null, 2)}</pre>
          </div>
        </div>
      </div>
    </div>
  );
}

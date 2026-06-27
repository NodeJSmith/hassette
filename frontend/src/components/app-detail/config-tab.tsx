import clsx from "clsx";
import { useEffect } from "preact/hooks";

import type { ConfigRecord, SchemaNode } from "../../api/config-view-types";
import type { AppConfigData } from "../../api/endpoints";
import { getAppConfig } from "../../api/endpoints";
import { useSignal } from "../../hooks/use-signal";
import { Card } from "../shared/card";
import { ConfigSchemaView, ExpandableValue } from "../shared/config-schema-view";
import { EmptyState } from "../shared/empty-state";
import { Spinner } from "../shared/spinner";
import styles from "./config-tab.module.css";

interface Props {
  appKey: string;
}

/** True when the value is a plain (non-array) object usable as a ConfigRecord. */
function isConfigRecord(val: unknown): val is ConfigRecord {
  return val !== null && typeof val === "object" && !Array.isArray(val);
}

function ConfigValue({ val }: { val: unknown }) {
  if (val === null || val === undefined) return <>—</>;
  if (typeof val === "object") return <ExpandableValue value={val} />;
  return <>{String(val)}</>;
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

function AppConfigContent({ appConfig, schema }: { appConfig: ConfigRecord; schema: SchemaNode | undefined }) {
  // ConfigSchemaView wraps each section in its own Card, so it renders unwrapped — matching
  // the global Config page. Only the schema-less fallback table needs a Card around it.
  if (schema) {
    return <ConfigSchemaView schema={schema} values={appConfig} emptyMessage="no configuration fields" />;
  }
  return (
    <Card variant="config">
      <SimpleConfigTable config={appConfig} />
    </Card>
  );
}

export function ConfigTab({ appKey }: Props) {
  const loading = useSignal(true);
  const error = useSignal<string | null>(null);
  const configData = useSignal<AppConfigData | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    loading.value = true;
    error.value = null;
    configData.value = null;

    async function load() {
      try {
        const data = await getAppConfig(appKey, controller.signal);
        if (controller.signal.aborted) return;
        configData.value = data;
      } catch (err) {
        if (controller.signal.aborted) return;
        error.value = err instanceof Error ? err.message : String(err);
      } finally {
        if (!controller.signal.aborted) loading.value = false;
      }
    }

    void load();
    return () => {
      controller.abort();
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
  const schema = cfg.config_schema ?? undefined;
  const isListConfig = Array.isArray(appConfig);

  return (
    <div class={styles.configTab} data-testid="config-tab-content">
      <div class={styles.layout}>
        <div class={styles.fieldsCard}>
          {isListConfig ? (
            <div class={styles.instances}>
              {/* isListConfig is a stored boolean, so TS can't use it to narrow
                  appConfig here — hence the cast despite the guard above. */}
              {(appConfig as unknown[]).map((instanceCfg, idx) => (
                <div key={idx} class={styles.instanceBlock} data-testid={`config-instance-${idx}`}>
                  <h4 class={styles.instanceHeading}>Instance {idx}</h4>
                  {isConfigRecord(instanceCfg) ? (
                    <AppConfigContent appConfig={instanceCfg} schema={schema} />
                  ) : (
                    <p class="ht-text-muted ht-text-sm">{String(instanceCfg)}</p>
                  )}
                </div>
              ))}
            </div>
          ) : isConfigRecord(appConfig) ? (
            <AppConfigContent appConfig={appConfig} schema={schema} />
          ) : (
            <EmptyState title="no configuration values" />
          )}
        </div>

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

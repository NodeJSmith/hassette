import { useEffect, useRef } from "preact/hooks";
import { signal } from "@preact/signals";
import { getAppConfig } from "../../api/endpoints";
import type { AppConfigData } from "../../api/endpoints";

interface Props {
  appKey: string;
}

type ConfigRecord = Record<string, unknown>;

/**
 * Single config key-value table for an object config.
 */
function ConfigTable({ config }: { config: ConfigRecord }) {
  // revealed[key] = true when revealed
  const revealed = useRef(signal<Record<string, boolean>>({})).current;

  const entries = Object.entries(config);
  if (entries.length === 0) {
    return (
      <div class="ht-config-tab__empty" data-testid="config-empty">
        <p class="ht-text-muted ht-text-sm">No configuration values.</p>
      </div>
    );
  }

  return (
    <table class="ht-table ht-config-tab__table" data-testid="config-values-table">
      <thead>
        <tr>
          <th class="ht-config-tab__col-key">Key</th>
          <th class="ht-config-tab__col-value">Value</th>
          <th class="ht-config-tab__col-action"></th>
        </tr>
      </thead>
      <tbody>
        {entries.map(([key, val]) => {
          const isRevealed = revealed.value[key] ?? false;

          return (
            <tr key={key}>
              <td>
                <code class="ht-text-mono ht-text-sm">{key}</code>
              </td>
              <td
                class="ht-config-tab__value"
                data-testid={`config-value-${key}`}
              >
                {isRevealed ? (
                  <code class="ht-text-mono ht-text-sm">{String(val ?? "")}</code>
                ) : (
                  <span class="ht-config-tab__redacted">••••••</span>
                )}
              </td>
              <td>
                <button
                  type="button"
                  class="ht-btn ht-btn--ghost ht-btn--xs"
                  data-testid={`reveal-btn-${key}`}
                  aria-label={isRevealed ? `Redact ${key}` : `Reveal ${key}`}
                  onClick={() => {
                    revealed.value = {
                      ...revealed.value,
                      [key]: !isRevealed,
                    };
                  }}
                >
                  {isRevealed ? "Redact" : "Reveal"}
                </button>
              </td>
            </tr>
          );
        })}
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
  }, [appKey, loading, error, configData]);

  if (loading.value) {
    return (
      <div class="ht-config-tab__loading" data-testid="config-tab-loading">
        <span class="ht-text-muted ht-text-sm">Loading config…</span>
      </div>
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

  // Multi-instance list config: array of config objects
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

      <div class="ht-config-tab__divider" />

      {/* Config values */}
      {isListConfig ? (
        // Multi-instance: render per-instance blocks
        <div class="ht-config-tab__instances">
          {(appConfig as unknown[]).map((instanceCfg, idx) => (
            <div
              key={idx}
              class="ht-config-tab__instance-block"
              data-testid={`config-instance-${idx}`}
            >
              <h3 class="ht-config-tab__instance-heading">Instance {idx}</h3>
              {instanceCfg && typeof instanceCfg === "object" && !Array.isArray(instanceCfg) ? (
                <ConfigTable config={instanceCfg as ConfigRecord} />
              ) : (
                <p class="ht-text-muted ht-text-sm">{String(instanceCfg)}</p>
              )}
            </div>
          ))}
        </div>
      ) : appConfig && typeof appConfig === "object" && !Array.isArray(appConfig) ? (
        <ConfigTable config={appConfig as ConfigRecord} />
      ) : (
        <div class="ht-config-tab__empty" data-testid="config-empty">
          <p class="ht-text-muted ht-text-sm">No configuration values.</p>
        </div>
      )}
    </div>
  );
}

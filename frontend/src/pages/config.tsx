import { useQuery } from "@tanstack/preact-query";

import { getConfig } from "../api/endpoints";
import { Card } from "../components/shared/card";
import { Spinner } from "../components/shared/spinner";
import { useDocumentTitle } from "../hooks/use-document-title";
import styles from "./config.module.css";

type ConfigRow = { key: string; value: string };

interface ConfigGroup {
  label: string;
  rows: ConfigRow[];
}

function formatValue(value: unknown): string {
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return String(value);
  if (Array.isArray(value)) return value.length === 0 ? "—" : value.join(", ");
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

export function ConfigPage() {
  useDocumentTitle("Config");
  const {
    data: config,
    isPending: loading,
    error,
  } = useQuery({
    queryKey: ["config"],
    queryFn: getConfig,
  });

  const groups: ConfigGroup[] = config
    ? [
        {
          label: "general",
          rows: [
            { key: "dev_mode", value: formatValue(config.dev_mode) },
            { key: "log_level", value: formatValue(config.logging?.log_level) },
            { key: "autodetect", value: formatValue(config.apps?.autodetect) },
            { key: "asyncio_debug_mode", value: formatValue(config.asyncio_debug_mode) },
            { key: "allow_reload_in_prod", value: formatValue(config.allow_reload_in_prod) },
          ],
        },
        {
          label: "connection",
          rows: [
            { key: "base_url", value: formatValue(config.base_url) },
            { key: "host", value: formatValue(config.web_api?.host) },
            { key: "port", value: formatValue(config.web_api?.port) },
            { key: "cors_origins", value: formatValue(config.web_api?.cors_origins) },
            { key: "run", value: formatValue(config.web_api?.run) },
            { key: "run_ui", value: formatValue(config.web_api?.run_ui) },
            { key: "ui_hot_reload", value: formatValue(config.web_api?.ui_hot_reload) },
            { key: "web_api_log_level", value: formatValue(config.logging?.web_api) },
          ],
        },
        {
          label: "buffers",
          rows: [
            { key: "event_buffer_size", value: formatValue(config.web_api?.event_buffer_size) },
            { key: "log_buffer_size", value: formatValue(config.web_api?.log_buffer_size) },
            { key: "job_history_size", value: formatValue(config.web_api?.job_history_size) },
          ],
        },
        {
          label: "timeouts",
          rows: [
            { key: "startup_timeout_seconds", value: formatValue(config.lifecycle?.startup_timeout_seconds) },
            { key: "app_startup_timeout_seconds", value: formatValue(config.lifecycle?.app_startup_timeout_seconds) },
            { key: "app_shutdown_timeout_seconds", value: formatValue(config.lifecycle?.app_shutdown_timeout_seconds) },
          ],
        },
        {
          label: "scheduler",
          rows: [
            { key: "min_delay_seconds", value: formatValue(config.scheduler?.min_delay_seconds) },
            { key: "max_delay_seconds", value: formatValue(config.scheduler?.max_delay_seconds) },
            { key: "default_delay_seconds", value: formatValue(config.scheduler?.default_delay_seconds) },
          ],
        },
        {
          label: "file_watcher",
          rows: [
            { key: "watch_files", value: formatValue(config.file_watcher?.watch_files) },
            { key: "debounce_milliseconds", value: formatValue(config.file_watcher?.debounce_milliseconds) },
          ],
        },
        {
          label: "paths",
          rows: [
            { key: "app_dir", value: formatValue(config.apps?.directory) },
            { key: "data_dir", value: formatValue(config.data_dir) },
            { key: "config_dir", value: formatValue(config.config_dir) },
          ],
        },
      ]
    : [];

  return (
    <div class="ht-page" data-testid="config-page">
      <div class="ht-page-header">
        <h1 class="ht-display">config</h1>
      </div>

      {loading && <Spinner />}

      {error && (
        <div class="ht-alert ht-alert--danger" role="alert">
          {error.message}
        </div>
      )}

      {config && (
        <div class={styles.groups}>
          {groups.map((group) => (
            <section key={group.label} class={`${styles.group} ht-mb-8`}>
              <h2 class="ht-section-label">{group.label}</h2>
              <Card variant="config">
                <table class={`ht-table ht-table--compact ${styles.configTable}`}>
                  <tbody>
                    {group.rows.map((row) => {
                      const valueClass =
                        row.value === "—"
                          ? `${styles.configTableValue} ${styles.configTableValueEmpty}`
                          : styles.configTableValue;
                      return (
                        <tr key={row.key}>
                          <td class={styles.configTableKey}>{row.key}</td>
                          <td class={valueClass} data-testid="config-value">
                            {row.value}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </Card>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}

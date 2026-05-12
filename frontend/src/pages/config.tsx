import { getConfig } from "../api/endpoints";
import { Spinner } from "../components/shared/spinner";
import { useApi } from "../hooks/use-api";
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
  const result = useApi(getConfig);
  const config = result.data.value;
  const loading = result.loading.value;
  const error = result.error.value;

  const groups: ConfigGroup[] = config
    ? [
        {
          label: "general",
          rows: [
            { key: "dev_mode", value: formatValue(config.dev_mode) },
            { key: "log_level", value: formatValue(config.log_level) },
            { key: "autodetect_apps", value: formatValue(config.autodetect_apps) },
            { key: "watch_files", value: formatValue(config.watch_files) },
            { key: "file_watcher_debounce_milliseconds", value: formatValue(config.file_watcher_debounce_milliseconds) },
            { key: "asyncio_debug_mode", value: formatValue(config.asyncio_debug_mode) },
            { key: "allow_reload_in_prod", value: formatValue(config.allow_reload_in_prod) },
          ],
        },
        {
          label: "connection",
          rows: [
            { key: "base_url", value: formatValue(config.base_url) },
            { key: "web_api_host", value: formatValue(config.web_api_host) },
            { key: "web_api_port", value: formatValue(config.web_api_port) },
            { key: "web_api_cors_origins", value: formatValue(config.web_api_cors_origins) },
            { key: "run_web_api", value: formatValue(config.run_web_api) },
            { key: "run_web_ui", value: formatValue(config.run_web_ui) },
            { key: "web_ui_hot_reload", value: formatValue(config.web_ui_hot_reload) },
            { key: "web_api_log_level", value: formatValue(config.web_api_log_level) },
          ],
        },
        {
          label: "buffers",
          rows: [
            { key: "web_api_event_buffer_size", value: formatValue(config.web_api_event_buffer_size) },
            { key: "web_api_log_buffer_size", value: formatValue(config.web_api_log_buffer_size) },
            { key: "web_api_job_history_size", value: formatValue(config.web_api_job_history_size) },
          ],
        },
        {
          label: "timeouts",
          rows: [
            { key: "startup_timeout_seconds", value: formatValue(config.startup_timeout_seconds) },
            { key: "app_startup_timeout_seconds", value: formatValue(config.app_startup_timeout_seconds) },
            { key: "app_shutdown_timeout_seconds", value: formatValue(config.app_shutdown_timeout_seconds) },
          ],
        },
        {
          label: "scheduler",
          rows: [
            { key: "scheduler_min_delay_seconds", value: formatValue(config.scheduler_min_delay_seconds) },
            { key: "scheduler_max_delay_seconds", value: formatValue(config.scheduler_max_delay_seconds) },
            { key: "scheduler_default_delay_seconds", value: formatValue(config.scheduler_default_delay_seconds) },
          ],
        },
        {
          label: "paths",
          rows: [
            { key: "app_dir", value: formatValue(config.app_dir) },
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
          {error}
        </div>
      )}

      {config && (
        <div class={styles.groups}>
          {groups.map((group) => (
            <section key={group.label} class={`${styles.group} ht-mb-8`}>
              <h2 class="ht-section-label">{group.label}</h2>
              <div class="ht-card ht-card--config">
                <table class={`ht-table ht-table--compact ${styles.configTable}`}>
                  <tbody>
                    {group.rows.map((row) => (
                      <tr key={row.key}>
                        <td class={styles.configTableKey}>{row.key}</td>
                        <td class={row.value === "—" ? `${styles.configTableValue} ${styles.configTableValueEmpty}` : styles.configTableValue} data-testid="config-value">{row.value}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}

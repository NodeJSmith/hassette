/**
 * Config-page test fixtures: a minimal `HassetteConfig` schema, default values,
 * and the `createSystemConfig` factory built from them.
 */

import type { components } from "../api/generated-types";

type ConfigSchemaResponse = components["schemas"]["ConfigSchemaResponse"];

/**
 * Minimal schema used in tests — mirrors the shape produced by the backend's
 * build_config_view for a small HassetteConfig subset.  Only the fields that
 * individual tests assert on need to appear here.
 */
const MINIMAL_CONFIG_SCHEMA = {
  type: "object",
  title: "HassetteConfig",
  properties: {
    dev_mode: { type: "boolean", title: "Dev Mode" },
    base_url: { type: "string", title: "Base Url", ui: { label: "Base URL" } },
    asyncio_debug_mode: { type: "boolean", title: "Asyncio Debug Mode" },
    allow_reload_in_prod: { type: "boolean", title: "Allow Reload In Prod" },
    data_dir: { type: "string", title: "Data Dir", format: "path" },
    config_dir: { type: "string", title: "Config Dir", format: "path" },
    token: {
      anyOf: [{ type: "string", writeOnly: true, format: "password" }, { type: "null" }],
      title: "Token",
    },
    web_api: {
      type: "object",
      title: "Web Api",
      ui: { group_label: "Web API" },
      properties: {
        run: { type: "boolean", title: "Run" },
        run_ui: { type: "boolean", title: "Run Ui", ui: { label: "Run UI" } },
        ui_hot_reload: { type: "boolean", title: "Ui Hot Reload", ui: { label: "UI Hot Reload" } },
        host: { type: "string", title: "Host" },
        port: { type: "integer", title: "Port" },
        cors_origins: {
          type: "array",
          title: "Cors Origins",
          ui: { label: "CORS Origins" },
          items: { type: "string" },
        },
        job_history_size: { type: "integer", title: "Job History Size" },
      },
    },
    logging: {
      type: "object",
      title: "Logging",
      properties: {
        log_level: { type: "string", title: "Log Level" },
        web_api: { type: "string", title: "Web Api" },
      },
    },
    lifecycle: {
      type: "object",
      title: "Lifecycle",
      properties: {
        startup_timeout_seconds: { type: "integer", title: "Startup Timeout Seconds" },
        app_startup_timeout_seconds: { type: "integer", title: "App Startup Timeout Seconds" },
        app_shutdown_timeout_seconds: { type: "integer", title: "App Shutdown Timeout Seconds" },
      },
    },
    apps: {
      type: "object",
      title: "Apps",
      properties: {
        autodetect: { type: "boolean", title: "Autodetect" },
        directory: { type: "string", title: "Directory", format: "path" },
      },
    },
    scheduler: {
      type: "object",
      title: "Scheduler",
      properties: {
        min_delay_seconds: { type: "number", title: "Min Delay Seconds" },
        max_delay_seconds: { type: "number", title: "Max Delay Seconds" },
        default_delay_seconds: { type: "number", title: "Default Delay Seconds" },
      },
    },
    file_watcher: {
      type: "object",
      title: "File Watcher",
      properties: {
        watch_files: { type: "boolean", title: "Watch Files" },
        debounce_milliseconds: { type: "integer", title: "Debounce Milliseconds" },
      },
    },
  },
};

/** Default config values to use in test fixtures. */
const DEFAULT_CONFIG_VALUES: Record<string, unknown> = {
  dev_mode: false,
  base_url: "",
  asyncio_debug_mode: false,
  allow_reload_in_prod: false,
  data_dir: "/config/data",
  config_dir: "/config",
  token: null,
  web_api: {
    run: true,
    run_ui: true,
    ui_hot_reload: false,
    host: "localhost",
    port: 8126,
    cors_origins: [],
    job_history_size: 1000,
  },
  logging: {
    log_level: "INFO",
    web_api: "INFO",
  },
  lifecycle: {
    startup_timeout_seconds: 30,
    app_startup_timeout_seconds: 20,
    app_shutdown_timeout_seconds: 10,
  },
  apps: {
    autodetect: true,
    directory: "/config/apps",
  },
  scheduler: {
    min_delay_seconds: 1,
    max_delay_seconds: 30,
    default_delay_seconds: 15,
  },
  file_watcher: {
    watch_files: true,
    debounce_milliseconds: 3000,
  },
};

/**
 * Build a ConfigSchemaResponse test fixture.
 *
 * Pass value-level overrides as a partial Record to merge into config_values.
 * Pass schemaOverrides to replace the entire config_schema.
 */
export function createSystemConfig(
  valueOverrides: Record<string, unknown> = {},
  schemaOverrides?: Record<string, unknown>,
): ConfigSchemaResponse {
  const config_values = { ...DEFAULT_CONFIG_VALUES, ...valueOverrides };
  const config_schema = schemaOverrides ?? MINIMAL_CONFIG_SCHEMA;
  return { config_schema, config_values } satisfies ConfigSchemaResponse;
}

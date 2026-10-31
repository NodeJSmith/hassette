# Inspect Configuration and Code

The web UI shows what configuration Hassette is running with and what the app code looks like. No SSH access needed.

## Check Running Configuration

### Global Configuration

![Global configuration page](../../_static/web_ui_config.png)

The Configuration page renders all `hassette.toml` values in schema-driven sections — one section per nested config group (`Web API`, `Logging`, `Lifecycle`, `Apps`, `Scheduler`, `File Watcher`, and others), plus a `General` section for top-level scalar fields. Section names and field labels come from the schema's `ui` metadata, not hardcoded strings.

Each field row shows its human-readable label, the exact `hassette.toml` key beside it, and the value. The field's type is implied by how the value renders, not by a separate label. Booleans appear as `true`/`false` badges. Filesystem paths sit in a monospace code box. Enums and short arrays render as chips. Secret fields show as `🔒 ••••••••`, masked server-side before transmission. An unset field shows `not set`. Where a field has a description, an info button (ⓘ) reveals it in a popover.

The page is accessible from the sidebar under **Config**.

Values reflect the configuration loaded at the most recent startup or reload (triggered from the [Manage Apps](manage-apps.md) page or by the file watcher). Refresh the browser after a reload to see updated values.

See [Configuration](../core-concepts/configuration/index.md) for the full settings reference.

### Per-App Configuration

![Per-app configuration tab](../../_static/web_ui_app_detail_config.png)

The **Config** tab on an app detail page shows the configuration values from `hassette.toml` for that app instance. Secret fields (`SecretStr`) are masked server-side and displayed as `🔒 ••••••••` — the plaintext never reaches the browser. When a schema is available for the app's `AppConfig`, the tab uses the shared schema renderer (same groups and formatting as the global Config page); apps without a schema fall back to a flat key-value table.

The tab shows the `config` values Hassette loaded for the app: `hassette.toml` plus any `HASSETTE__APPS__<APP_KEY>__CONFIG__<FIELD>` environment overrides. It omits [`AppConfig`](../core-concepts/apps/index.md) field defaults and values read through `env_prefix`, the prefix an `AppConfig` uses to read environment variables directly. Hassette applies those when it validates the app's config, so their absence from the tab is normal. Validation still happens at startup — missing required fields and wrong types surface as startup errors rather than silent misconfiguration.

The tab is on the app detail page, accessible by selecting an app from the sidebar.

If a `HASSETTE__APPS__<APP_KEY>__CONFIG__<FIELD>` override doesn't appear in the tab, its name doesn't match the app key and field (see [App Configuration](../core-concepts/apps/configuration.md)). The tab can't confirm an `env_prefix` variable (see [Environment Variables](../core-concepts/apps/index.md#environment-variables)). A value set in `hassette.toml` takes precedence over an `env_prefix` variable. To check what the app received, log `self.app_config.<field>` in `on_initialize`.

## Read App Source Code

![Code tab](../../_static/web_ui_app_detail_code.png)

The **Code** tab on an app detail page displays the Python source of the app as deployed. The view is read-only and syntax-highlighted.

If Hassette runs in Docker, the container's app directory may differ from your local copy. The Code tab shows what is on disk inside the running container, without needing a shell.

The tab is on the same app detail page as the Config tab.

## See Also

- [Web UI Overview](index.md): enabling, accessing, and layout
- [Configuration](../core-concepts/configuration/index.md): all available settings and how to change them
- [Apps](../core-concepts/apps/index.md): `AppConfig` fields and environment variable conventions

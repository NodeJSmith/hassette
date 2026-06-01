# Configuration — Global Settings

**Status:** Exists (313 lines), dense reference, voice polish needed
**Voice mode:** Reference — tabular, terse, system-as-subject

## Outline

Long reference page documenting every global setting in hassette.toml. Keep current structure — it's a lookup reference.

### H2: Connection Settings
`host`, `port`, `ssl_verify`, `token` location.

### H2: Runtime Settings
`auto_reload`, `app_dir`, `project_dir`.

### H2: Storage Settings
`data_dir`, `cache_dir`.

### H2: Web UI Settings
`web_enabled`, `web_host`, `web_port`, CORS, static files.

### H2: Database Settings
`db_path`, `db_retention_days`.

### H2: Timeout Settings
#### H3: WebSocket Resilience — reconnection, sliding window budget, backoff
#### H3: Timeouts — per-item overrides, disabling, limitations

### H2: Scheduler Settings
Default scheduler configuration.

### H2: Logging Settings
Log level, format.

### H2: Bus Filtering Settings
Default bus filter behavior.

### H2: Production Settings
Settings recommended for production.

### H2: App Detection Settings
How Hassette finds apps.

### H2: Advanced Settings
Rarely-changed settings.

### H2: Service Restart Policy
Default RestartSpec configuration.

### H2: Other Advanced Settings

### H2: Basic Example
Complete hassette.toml example.

## Snippet Inventory

No code snippets — TOML examples are inline.

## Cross-Links

- **Links to:** Configuration overview, Operating/Log Levels (log settings detail)
- **Linked from:** Configuration overview, Docker Setup, Operating

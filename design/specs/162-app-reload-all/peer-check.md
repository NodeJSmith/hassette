# Peer check: reload-all decisions (2026-11-27)

Supplements `design/research/2026-11-27-helper-module-reload/research.md` with what peers do on this ledger's decisions. Sources are shallow clones of AppDaemon, HA core and pyscript (read only) plus the cited URLs.

- **Which apps (D1).**
  - AppDaemon `admin/app/reload` (`app_management.py` `check_app_updates(mode=RELOAD_APPS)`) seeds the reload set with the running apps.
  - `check_app_config_files` then starts every configured app that isn't running, isn't `disable`d, and isn't `compile_error`.
  - Docs: an app that errored mid-run "will only be reloaded when next the app's file has been changed" (`docs/APPGUIDE.rst`).
  - pyscript.reload restarts every global context, with no filter for running ones.
  - HA `reload_config_entry` loads an entry that wasn't loaded.
- **Bursts (D5).** Every peer found uses a fixed window or a poll, and none checks mtime stability.
  - pyscript drains events up to 50 ms apart, for at most 500 ms.
  - watchfiles defaults to `debounce=1600`, `step=50`.
  - AppDaemon (`utility_delay` 1 s) and Django's `StatReloader` both poll every 1 s.
- **Config (D7).** Every peer re-reads config on reload.
  - AppDaemon re-reads `apps.yaml` on each pass.
  - pyscript re-reads its YAML first.
  - HA `reload_all` runs `async_check_ha_config_file` first and raises on an invalid config before reloading anything (`components/homeassistant/services.py`).
- **Busy (D6).** Peers serialize rather than reject.
  - AppDaemon serializes on `check_updates_lock`, so a second call waits and then runs. Its HTTP service fires and forgets, answering 200.
  - HA service calls block.
  - kubectl and Helm have a caller-chosen `--wait`.
- **Partial failure (D8).**
  - HA `reload_all` raises on the first domain failure, with no per-item results.
  - AppDaemon and pyscript only log failures (AppDaemon's HTTP answers 200).
- **CLI (D10).**
  - kubectl declined an `--all` flag (kubernetes/kubectl#1751); a command with no name means all.
  - pm2 and supervisorctl use a positional `all` keyword.
  - AppDaemon has no reload CLI.
  - HA has a separate `reload_all` service.
- **Batch results (D8, revisited in the sketch challenge).** Elasticsearch `_bulk` always answers 200, with a top-level `errors` flag and a per-item `status`/`error` (https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-bulk). It declined to adopt 207 because 207 belongs to WebDAV (elastic/elasticsearch#60442). Zalando's REST guidelines recommend 207 Multi-Status for batch requests with mixed per-item results. No API was found that answers an error status and puts per-item results in the error body.

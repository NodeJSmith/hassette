# App Detail

The App Detail page gives you a focused view of a single app — its health, handlers, source
code, logs, and configuration. You reach it by clicking any app key in the
[Apps page](../apps.md) or in the sidebar.

The page is divided into tabs. Each tab addresses one concern: the overview tab for at-a-glance
health monitoring, the handlers tab for drill-down into individual handlers and jobs, the code
tab for viewing the source file, the logs tab for per-app log entries, and the config tab for
the app's current configuration.

## Breadcrumb

The breadcrumb at the top of the page shows your location within the web UI:

- **Single-instance apps** — `apps / <app_key>`
- **Multi-instance apps, instance view** — `apps / <app_key> / <instance_name>`

The `apps` segment is a link back to the Apps page. For multi-instance apps the `<app_key>`
segment is a link to the parent overview.

## Header

The header shows the app's identity and primary actions:

- **Status dot** — reflects the app's current lifecycle state (green = running, red = failed,
  gray = stopped or disabled)
- **App key** — the registered name of the app
- **Action buttons** — context-sensitive based on current status:

| Button | Available when | Effect |
|--------|---------------|--------|
| **Reload** | running | Reloads the app, picking up code and config changes |
| **Stop** | running | Stops the app (shows a confirmation dialog) |
| **Start** | stopped, failed, or disabled | Starts (or restarts) the app |

Below the app key, a metadata line shows:

- **Filename** — the Python file the app is loaded from
- **Class name** — the Python class name (only shown when it differs from the app key)
- **"auto" chip** — shown when the app was discovered by directory scan rather than an explicit
  `hassette.toml` entry
- **Instance index** — shown for multi-instance apps when viewing a specific instance (e.g.,
  `· instance 1`)

If the app has an unhandled error at the app level (not just a handler failure), an error banner
appears below the metadata line with the error message and a "show traceback" link.

## Instance switcher

![Instance switcher](../../../_static/web_ui_detail_instance_switcher.png)

On multi-instance apps, when you are viewing a specific instance (not the parent overview), an
instance switcher appears between the breadcrumb and the header. It shows one button per
instance, each with:

- A status dot reflecting that instance's current state
- The instance name

Click any button to switch to that instance. The active instance button is highlighted. Tab
content (handlers, logs, etc.) updates immediately to reflect the selected instance.

!!! note
    The instance switcher is only visible when you are on an instance view. On the parent
    overview (no instance selected), only the tab strip is shown.

## Tab strip

The tab strip below the header provides navigation between the five tabs:

| Tab | Description |
|-----|-------------|
| **overview** | Handler health grid, error spotlight, recent activity, and embedded logs. The default tab when navigating to App Detail. |
| **handlers** (with count badge) | Master-detail handler and job explorer with stats, modifier chips, source location, and invocation history. The badge shows the total number of handlers and scheduled jobs. |
| **code** | Syntax-highlighted source file with line numbers and handler annotations. |
| **logs** | Per-app log table scoped to this app, with the same filter and search features as the global Logs page. |
| **config** | App metadata and a typed configuration table showing the current value of every config field. |

Each tab is documented on its own page — see [Related pages](#related-pages) below.

!!! note
    On multi-instance apps, the **handlers** tab is hidden on the parent overview. It becomes
    available once you select an instance.

## Multi-instance parent overview

When you navigate to a multi-instance app without selecting a specific instance, the overview
tab shows a grid of instance cards instead of the per-instance content. Each card displays:

- Status dot + instance name
- Status badge (running, failed, stopped, etc.)
- Error message preview (if the instance has a current error)

Click any card to navigate to that instance. Once you select an instance, the instance switcher
appears and all tab content is scoped to that instance.

The parent overview lets you assess the health of all instances before deciding which one to
investigate.

## Related pages

- [Apps](../apps.md) — back to the full app list
- [Overview Tab](overview.md) — handler health at a glance, error spotlight, recent activity
- [Handlers Tab](handlers.md) — drill into individual handler and job details
- [Code Tab](code.md) — view and navigate the app's source file
- [Logs Tab](logs.md) — per-app log entries with search and filtering
- [Config Tab](config.md) — app metadata and typed configuration fields

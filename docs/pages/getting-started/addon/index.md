# Add-on Setup

Run Hassette inside Home Assistant with the add-on. It connects to Home Assistant with no token to paste and puts the web UI in your sidebar.

!!! note "Add-ons and apps"
    Newer Home Assistant versions call add-ons "apps" in their menus, so you see **Apps** in the paths below. These are not Hassette apps. A Hassette app is your automation code, which you edit in Step 4.

This page needs Home Assistant OS or Supervised. On Home Assistant Container or Core, which have no add-on support, use [Docker Setup](../docker/index.md) instead.

## What You'll Build

- A running Hassette add-on with the web UI in your sidebar.
- A first app you edit, with your change showing in the log.
- The Hassette integration, paired without typing an address or token.

## Prerequisites

- **amd64 or aarch64 hardware.** The add-on ships images for these two. On other hardware, run Hassette with [Docker](../docker/index.md) on another machine.
- **A way to edit files in the add-on's config folder.** The Samba share, File editor, or Studio Code Server add-on all work.
- **[HACS](https://hacs.xyz)**, for Step 5 only. Hassette's integration installs through it. Steps 1 to 4 work without it.

## Step 1: Add the repository

Choose the badge to add the Hassette repository to your Home Assistant:

[![Add repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FNodeJSmith%2Fhassette-addon)

Or add it by hand:

1. Open **Settings → Apps → App store**.
2. Choose **Repositories** from the ⋮ menu.
3. Add `https://github.com/NodeJSmith/hassette-addon`.

## Step 2: Install and turn on Watchdog

1. In the **App store**, open **Hassette** and choose **Install**.
2. On the add-on's **Info** tab, turn on **Watchdog**.

Watchdog restarts Hassette if it crashes or fails its health check. Without it, a stopped add-on stays stopped until you start it again. See [Watchdog](operating.md#watchdog) for the exact rules.

## Step 3: Start it

1. On the **Info** tab, choose **Start**.
2. Open the **Log** tab and wait for the line containing `Hassette is running.`
3. Open **Hassette** in the Home Assistant sidebar.

On first start, the log includes these lines. Your timestamps differ, and you can skip everything else for now:

```text
The config folder is empty; adding a starter hassette.toml and an example app
Port mappings: none (ingress only)
2026-10-17T08:19:58.690526 [info     ] Generated new web API auth_token, written to /config/.web_api_token. Open Hassette from the Home Assistant sidebar or the add-on's "Open Web UI" button; the token is only needed for the hassette CLI or a published port. [hassette.web.auth.tokens] execution_id=None
2026-10-17T08:19:58.690609 [info     ] Hassette is running.           [hassette] execution_id=None
2026-10-17T08:19:58.690670 [info     ] Hello from Hassette! Edit example_app.py in the apps folder of the add-on's config folder. [hassette.apps.example_app] execution_id=None
Announced hassette to Home Assistant; the hassette integration can now be set up from its Discovered card
```

The first line means the add-on filled your empty config folder with starter files. It added a `hassette.toml` and an `apps/` folder holding one example app. If the folder already holds files, the add-on writes nothing. The announce line can land before or after the app's greeting.

Home Assistant's own login covers the web UI, so Hassette has no separate login. The sidebar entry shows for admin users only, so sign in as an admin if you don't see it. See [Web UI and Direct Port](configuration.md#web-ui-and-direct-port) for access details.

If the log shows an error banner instead, see [Troubleshooting](operating.md#troubleshooting).

## Step 4: Edit your first app

```python
--8<-- "pages/getting-started/addon/snippets/example_app.py"
```

This is the starter app, `example_app.py`. [`AppConfig`](../../core-concepts/apps/configuration.md) loads and validates your app's settings. `greeting` is one setting, with a default value. `App[ExampleAppConfig]` pairs the app with that config class, so `self.app_config` knows its type.

[`App`](../../core-concepts/apps/index.md) runs your automation and gives it a logger, the event bus, the scheduler and the API. Its `on_initialize` hook runs when the app starts. Here, it logs the greeting through `self.logger`. Hooks are `async def`, and Hassette runs the event loop for you.

Find the file in your config folder:

1. Open the Samba share, File editor, or Studio Code Server.
2. Go to `app_configs/`, then to the folder ending in `_hassette`.
3. Open `apps/example_app.py`.

Replace the `greeting` default with your own text, such as `"Hello from my first Hassette app!"`, then save the file.

The starter `hassette.toml` already has the example app's section, so the edit needs no config change. Restart the add-on from its **Info** tab, then open the **Log** tab again. You see a line like this with your new greeting:

```text
2026-10-17T08:24:11.102394 [info     ] Hello from my first Hassette app! [hassette.apps.example_app] execution_id=None
```

To give the app settings of its own, set them in its section's `config` in `hassette.toml`. The starter file shows the format in a comment, and [Add-on Configuration](configuration.md#hassettetoml) explains it.

## Step 5: Pair the integration

The Hassette integration turns each app into a Home Assistant device you can start, stop, and reload. Follow [Step 1 of Control Apps from Home Assistant](../home-assistant-integration.md#step-1-add-the-repository-in-hacs) to install it through HACS, then return here. Skip that page's token and form steps. The add-on supplies the address and token.

1. Open **Settings → Devices & services**.
2. Find the **Discovered** Hassette card.
3. Choose **Configure**, then confirm.

The Hassette integration now lists a device for each app, including one for the example app. Its switch starts and stops the app.

The card appears only after Hassette is serving. If you don't see it, check the **Log** tab for the `Announced hassette to Home Assistant` line, then see [The Discovered card never appears](operating.md#the-discovered-card-never-appears).

!!! warning "Confirm only a card you expect"
    Pairing gives the integration the add-on's web API token, and the integration stores it. Confirm a Hassette card only when you run the Hassette add-on.

## Next Steps

- [First Automation](../first-automation.md): subscribe to events and control devices.
- [Add-on Configuration](configuration.md): options, files, owned settings, and dependencies.
- [Watchdog, Backups & Troubleshooting](operating.md): keep the add-on running and recover when it doesn't.
- [Control Apps from Home Assistant](../home-assistant-integration.md): what the integration gives you.

# Control Apps from Home Assistant

The Hassette integration for Home Assistant turns each Hassette app into a Home Assistant device. You install it through HACS from [`NodeJSmith/hass-hassette`](https://github.com/NodeJSmith/hass-hassette). Then you start, stop, and reload apps from dashboards and automations.

## What You'll Get

Each app gets a device named after its display name. The display name defaults to the app key, the `<key>` in its `[hassette.apps.<key>]` block. An auto-detected app with no block uses its class name instead. Set `display_name` to choose the name yourself. For an app keyed `motion_lights`, the integration creates:

- **`switch.motion_lights`**: on while the app is `running` or `degraded`. Turn it off to stop the app, on to start it.
- **`button.motion_lights_reload`**: stops the app, re-imports its code from disk, and starts it again.
- **`sensor.motion_lights_status`**: the app's current status.

Run `hassette app` to see each app's key and display name. Every app device shows **Connected via Hassette**, a hub device for the server itself.

## Prerequisites

- **Hassette 0.56.0 or newer**, running where Home Assistant can reach its web API over the network. Hassette does not run as a Home Assistant add-on, so it runs on another machine or in its own container.
- **HACS** installed in Home Assistant.
- **Home Assistant 2026.9 or newer**.

## Step 1: Add the Repository in HACS

1. In Home Assistant, open **HACS**.
2. Open the three-dot menu and choose **Custom repositories**.
3. Enter `https://github.com/NodeJSmith/hass-hassette` as the repository and choose **Integration** as the type.
4. Find **Hassette** in HACS and download it.
5. Restart Home Assistant from **Settings → System → Restart**.

## Step 2: Get Hassette's Web API Token

```bash
--8<-- "pages/getting-started/docker/snippets/read-web-api-token.sh"
```

The output is one line: the token Hassette generated on its first start. Outside Docker, read `<data_dir>/.web_api_token` instead. The startup log names that path, on a line beginning `Generated new web API auth_token` on first start and `Loaded existing web API auth_token` after that. The log never prints the token itself.

To set your own token instead, add it to `hassette.toml` and restart Hassette. From then on, use that value, not the file:

```toml
--8<-- "pages/getting-started/snippets/hassette_web_api_token.toml"
```

The `HASSETTE__WEB_API__AUTH_TOKEN` environment variable does the same, and keeps the token out of `hassette.toml`. It's the same credential the web UI login and the CLI use.

## Step 3: Add the Integration

1. In Home Assistant, go to **Settings → Devices & services**.
2. Choose **Add integration** and search for **Hassette**.
3. Fill in the form, then submit.

| Field | Value |
|---|---|
| **URL** | Hassette's address and port, as Home Assistant sees it. Example: `http://192.168.1.10:8126`. Port `8126` is the default web API port. |
| **API token** | The token from step 2. |
| **Verify SSL certificate** | On by default. Turn it off only for a self-signed certificate. |

Pick the URL by where the two run:

- **Separate machines**: use the LAN IP or hostname of the machine running Hassette.
- **One Docker Compose project**: use the service name, such as `http://hassette:8126`.
- **Same machine, Home Assistant on host networking**: `http://127.0.0.1:8126` works when Hassette publishes port `8126`.

The integration checks the URL, the token, and the Hassette version before it saves anything. On success, Home Assistant lists a device for each app. Assign areas if you like, then choose **Finish**.

If the form shows an error, find it here:

| Message | Cause and fix |
|---|---|
| "Failed to connect to hassette. Check the URL, and that Home Assistant can reach it." | The address or port is wrong, or the network blocks the connection. Check the URL against the list above. |
| "Timed out connecting to hassette." | Nothing answered in time. Check that Hassette is running and the port is open. |
| "Enter an http:// or https:// URL without a username or password in it, such as http://192.168.1.10:8126." | The URL is malformed. Enter it with `http://` or `https://` and no credentials. |
| "hassette rejected the token." | The token does not match. Copy it again from step 2. |
| "hassette needs a token from Home Assistant's address. Enter a web API token, or list Home Assistant's address in hassette's web_api.trusted_proxies." | You left **API token** blank. Enter the token, or see [Without a Token](#without-a-token). |
| "hassette's API redirected to ..." | A login page in front of Hassette caught the request. See [Behind a Reverse Proxy](#behind-a-reverse-proxy). If the target is the `https` form of your URL, use that URL instead. |
| "hassette's API refused the request (403)..." | A proxy or firewall in front of Hassette blocks Home Assistant. Allow Home Assistant's address through. |

If the form stops with "hassette ... serves API schema ..., but this integration needs schema ... or newer", your Hassette is too old for the integration. [Upgrade Hassette](../operating/upgrading.md) and add the integration again.

Home Assistant connects to one Hassette server and refuses a second entry. To point at a different server, choose **Reconfigure** on the existing entry.

## Step 4: Use It

1. Go to **Settings → Devices & services → Hassette**.
2. Open an app's device. **Controls** shows its switch, **Sensors** shows **Status**, and **Configuration** shows **Reload**.

The switch and sensor work in dashboards and automations like any other entity:

```yaml
--8<-- "pages/getting-started/snippets/automation_stop_app.yaml"
```

This automation turns `switch.motion_lights` off at 23:00. Paste it into **Settings → Automations & scenes → Create automation → Edit in YAML**, with your own entity in place of `switch.motion_lights`. Call `switch.turn_on` to start the app, or `button.press` on `button.motion_lights_reload` to reload it.

!!! warning "A stop lasts until Hassette restarts or reloads the app"
    When Hassette restarts, it starts every enabled app that has `autostart` on, including one you stopped here. With automatic reloads on (`dev_mode` or `allow_reload_in_prod`), editing the app's code or config starts it again too. To keep an app off until you switch it on, set `autostart = false` in its `[hassette.apps.<key>]` block. The switch still starts it on demand. See [App Configuration](../core-concepts/apps/configuration.md).

`sensor.motion_lights_status` reports one of these states:

| State | Meaning |
|---|---|
| `running` | The app runs. |
| `degraded` | Some instances run and at least one has failed. |
| `failed` | The app failed. |
| `stopped` | The app is stopped. |
| `disabled` | The app has `enabled = false` in its config. |
| `blocked` | Hassette was started with `--app` and this app isn't in the list. |
| `unknown` | Hassette reports a status newer than your installed integration understands. Update the integration. |

While an app is `failed` or `degraded`, the sensor carries an `error_message` attribute with the app's error text.

## Reaching Hassette from Home Assistant

### Same LAN

Point the URL at Hassette's LAN address and port. The web API listens on every interface by default (`web_api.host` is `0.0.0.0`). In Docker, publish port `8126` too.

### Behind a Reverse Proxy

A reverse proxy with forward auth, such as Authelia, Authentik, or Traefik forward-auth, answers Home Assistant with its login page. The form then shows the "redirected to" error.

The simplest fix is to point the URL straight at Hassette's LAN address, skipping the proxy. To keep the proxy, add a route that matches `/api/*` on the same host, skips the forward-auth middleware, and forwards straight to Hassette. Hassette's own token then authenticates those requests. The CLI needs the same bypass, described in [Letting CLI Traffic Through a Reverse Proxy](../cli/configuration.md#letting-cli-traffic-through-a-reverse-proxy).

### Without a Token

```toml
--8<-- "pages/getting-started/snippets/hassette_trusted_proxies.toml"
```

Leave **API token** blank. In `web_api.trusted_proxies`, list the address Home Assistant's requests arrive from. That may be a Docker gateway like `172.17.0.1` rather than Home Assistant's LAN IP. Hassette then admits requests from that address that send no `Authorization` header. A request that sends a token is still checked against `auth_token`. See [Web UI](../web-ui/index.md#enabling-and-accessing) for how `trusted_proxies` matches addresses.

!!! warning "Trusting an address trusts everything behind it"
    Every process that reaches Hassette from that address gets full access to its API. On Home Assistant OS, add-ons usually reach other machines from Home Assistant's address too. Use a token unless you control everything on that address.

## Good to Know

- **Polling.** The integration checks Hassette every 30 seconds. A switch flip or button press refreshes every entity as soon as Hassette answers. Changes made in the web UI or the CLI show on the next check.
- **Disabled and blocked apps.** These apps keep their status sensor, but their switch and reload button are unavailable. Hassette can't start them from Home Assistant. Set `enabled = true`, or drop the `--app` filter, to control them again.
- **Hassette unreachable or starting.** Entities become unavailable after two missed checks, about a minute. The integration retries on its own. They're also unavailable until Hassette connects to Home Assistant and starts its apps. If they stay unavailable, check that connection with `hassette status`.
- **Removed apps.** Hassette keeps listing removed apps from its history, so their entities stay, unavailable. Delete the device from its device page to clear it.
- **Token changes.** Home Assistant asks you to re-authenticate: "hassette at {url} rejected the stored token. Enter its current web API token."
- **Connection changes.** Choose **Reconfigure** on the integration to change the URL, token, or SSL check. Devices and their settings are kept.

When a switch flip or button press fails, Home Assistant shows one of these:

| Message | What to do |
|---|---|
| "The app failed: ..." | The start, stop, or reload ran, but the app failed. Check its logs with `hassette log --app <key>`. |
| "Another action on this app is still running. Try again when it finishes." | Wait for the earlier start, stop, or reload to finish. |
| "hassette didn't confirm the action in time. It may still have run; ..." | Check the status sensor after the next refresh. |
| "hassette hasn't finished starting up, so apps can't be started yet. Try again shortly." | Wait for Hassette to connect to Home Assistant and start its apps. If it doesn't, run `hassette status`. |

## Next Steps

- [Manage Apps](../web-ui/manage-apps.md): start, stop, and reload apps from Hassette's own UI
- [App Lifecycle](../core-concepts/apps/lifecycle.md): the states an app moves through
- [Web UI](../web-ui/index.md): app health, invocation history, and logs in the browser

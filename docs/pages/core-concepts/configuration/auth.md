# Authentication & Secrets

Hassette needs a long-lived access token to authenticate with your Home Assistant instance. This page covers how to supply that token securely.

## Home Assistant Token

Create a long-lived access token in Home Assistant under your user profile, then supply it to Hassette using one of these methods:

| Method | How |
|--------|-----|
| Environment variable (recommended) | `HASSETTE__TOKEN=your_token_here` |
| `.env` file | Add `HASSETTE__TOKEN=your_token_here` to `.env` in your config directory |
| CLI flag | `hassette --token your_token_here` |

!!! note "Compatibility aliases"
    Hassette also accepts `HOME_ASSISTANT_TOKEN` and `HA_TOKEN` for compatibility with other tools, but `HASSETTE__TOKEN` is the canonical name and is recommended for new installations.

!!! warning "Never commit your token to version control"
    Store the token in an environment variable or a `.env` file that is listed in `.gitignore`. If you accidentally commit a token, rotate it immediately in Home Assistant.

If you do not have a token yet, follow the [Creating a Home Assistant Token](../../getting-started/ha_token.md) guide.

## SSL Verification

By default, Hassette verifies SSL certificates when connecting to Home Assistant. If you use a self-signed certificate or an internal CA that your system does not trust, disable verification in `hassette.toml`:

```toml
[hassette]
verify_ssl = false
```

!!! warning "Only disable SSL verification on trusted internal networks"
    Disabling SSL verification removes protection against man-in-the-middle attacks. Use it only when connecting to a trusted Home Assistant instance on a private network.

## File Locations

For details on where Hassette looks for configuration and `.env` files, see [Configuration Overview — File Locations](index.md#file-locations).

## See Also

- [Global Settings](global.md) — connection and runtime settings
- [Applications](applications.md) — app registration and configuration
- [Creating a Token](../../getting-started/ha_token.md) — step-by-step token creation

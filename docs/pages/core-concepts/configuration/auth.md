# Authentication & Secrets

Hassette needs to authenticate with your Home Assistant instance.

## Home Assistant Token

Create a long-lived access token from your Home Assistant profile and supply it via:

- **Environment variables**: `HASSETTE__TOKEN` (canonical).
- **CLI flags**: `--token` / `-t`.

!!! note "Compat env vars"
    Hassette also accepts `HOME_ASSISTANT_TOKEN` and `HA_TOKEN` for compatibility, but `HASSETTE__TOKEN` is recommended.

!!! note

    If you don't have a token yet, you can follow the steps in the [Creating a Home Assistant token](../../getting-started/ha_token.md) guide.

!!! warning "Security First"
    Never commit your access token to version control. Always use environment variables or a local `.env` file that is git-ignored.

## File Locations

For details on where Hassette looks for configuration and `.env` files, see [Configuration Overview — File Locations](index.md#file-locations).

## See Also

- [Global Settings](global.md) - Connection and runtime settings
- [Applications](applications.md) - App registration and configuration
- [Creating a Token](../../getting-started/ha_token.md) - Step-by-step token creation

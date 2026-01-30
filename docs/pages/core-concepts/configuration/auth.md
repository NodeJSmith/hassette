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

Hassette looks for configuration in these locations (in order):

- TOML: `/config/hassette.toml`, `./hassette.toml`, `./config/hassette.toml`
- Env: `/config/.env`, `./.env`, `./config/.env`

## Config File

Hassette will look for a file named `hassette.toml` in the above locations, stopping at the first match.

You can provide a specific path to the config file with the `--config-file` / `-c` CLI flag.

## Environment Files

Hassette searches for `.env` files in the same locations as config files.

You can override this with the `--env-file` / `-e` CLI flag.

Override either path with `--config-file / -c` and `--env-file / -e`:

```bash
# override both config and env file locations
hassette -c ./config/hassette.dev.toml -e ./config/.dev.env
```

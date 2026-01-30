# Getting Started

This section is intentionally streamlined:

- Use [First Run](first-run.md) for the fastest setup.
- Use [Docker Deployment](docker/index.md) if you’re running in production.
- Use the pages below for focused reference (token, config files)

## Prerequisites

- A running Home Assistant instance with WebSocket API access.
- A long-lived access token: [Creating a Home Assistant token](ha_token.md).
- Python 3.11+.

## Common commands

```bash
pip install hassette
hassette
```

!!! tip
    If your environment doesn't expose the `hassette` command, run `python -m hassette` instead.

## Where to go next

- Token help: [Creating a Home Assistant token](ha_token.md)
- Config file details: [Configuration Files](configuration.md)
- App authoring: [Apps Overview](../core-concepts/apps/index.md)
- Full configuration reference: [Configuration Overview](../core-concepts/configuration/index.md)

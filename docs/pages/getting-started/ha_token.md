# Creating a Home Assistant Token

Hassette authenticates to Home Assistant using a long-lived access token. You generate it once in the Home Assistant UI and store it in your `.env` file.

## Steps

1. Go to the [Profile](https://my.home-assistant.io/redirect/profile/) page in your Home Assistant instance. Click the **Security** tab.

   ![Home Assistant Profile Security Tab](../../_static/ha-profile-page.png)

2. Scroll down to **Long-Lived Access Tokens** and click **Create Token**.

   ![Create Long-Lived Access Token](../../_static/ha-create-token.png)

3. Enter a name, for example [`Hassette`][hassette.core.core.Hassette], and click **OK**.

   ![Name Long-Lived Access Token](../../_static/ha-token-name.png)

4. Copy the token. Home Assistant shows it only once. If you lose it, revoke it from the Security tab and create a new one.

   ![Copy Long-Lived Access Token](../../_static/ha-copy-token.png)

## What to Do with the Token

Add the token to your `.env` file:

```bash
--8<-- "pages/getting-started/snippets/env_token.sh"
```

The [Quickstart](index.md) covers the full `.env` setup and how to start Hassette. The [Docker Setup](docker/index.md) covers container-specific configuration.

!!! warning "Token security"
    A long-lived access token has the same permissions as your Home Assistant user account. Never commit it to version control or share it publicly. If a token is exposed, revoke it immediately from the Security tab and generate a new one.

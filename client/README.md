# hassette-client

Typed async client for the [Hassette](https://github.com/nodejsmith/hassette) HTTP API.

```python
import aiohttp
from hassette_client import HassetteClient

async with aiohttp.ClientSession() as session:
    client = HassetteClient(session, "http://127.0.0.1:8126", token="...")
    health = await client.get_health()
```

Every method returns a `hassette-wire` model, and every failure raises a `HassetteClientError`
subclass. The client uses the `aiohttp.ClientSession` you pass in and never opens or closes one.
Responses parse leniently, so the client keeps working against a newer server.

Full guide: [Call the API from Python](https://hassette.readthedocs.io/en/stable/pages/web-ui/python-client/).

This package is released in lockstep with `hassette` and `hassette-wire`.

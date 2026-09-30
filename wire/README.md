# hassette-wire

The wire contract for the [Hassette](https://github.com/nodejsmith/hassette) HTTP and WebSocket API:
request/response models and wire enums shared by the server and its clients.

This package is released in lockstep with `hassette` and `hassette-client`.

A wire field added after the first published release must be optional with a default, so a
client built against a newer release can still parse a response from a server still running an
older release that hasn't added the field yet. See the `hassette_wire` package docstring for the
full rule, including the enum/Literal version-skew case (the opposite direction: an older client
tolerating a newer server's added value).

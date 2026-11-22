# REVIEW.md — hassette_client/

## Exception Mapping
Can any new or changed path let a raw `aiohttp`, `asyncio` or `pydantic` exception escape a public
method, or does every network and server failure reach the caller as a `HassetteClientError`
subclass? Trace each `except` in `transport.py` and `stream.py`: does it map through
`Transport.failure()` or `error_class_for()`, or invent its own message, and does the message keep
`base_url`'s userinfo out?

## Lenient Parsing
Does every body or WebSocket frame parse through `parsing.parse_payload` with `LENIENT_CONTEXT`, so
an unknown field or enum value from a newer server never fails the call? Does a new path parse a
type the caller didn't ask for, which would let an unrelated server change break it?

## API Schema Floor
Does the change make the client send a route, method or query parameter, or require a response
field, that the floor release's API lacks? If so, does the PR bump `MIN_API_SCHEMA_VERSION` as its
docstring in `version.py` describes, and does a new public coroutine method appear in `CALLS` or
`WEBSOCKET_METHODS` in `client/tests/test_openapi_coverage.py`?

## Sibling Parity
A new public method on `HassetteClient`: does its docstring list every exception it raises, as the
siblings' do, and does it avoid retrying or reconnecting, since the class promises it never retries?

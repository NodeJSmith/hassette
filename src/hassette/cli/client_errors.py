"""Error and exit rendering for :class:`hassette.cli.client.HassetteCLIClient`.

Human mode prints Rich-formatted errors to stderr; JSON mode writes one JSON error document to
stdout. Every handler exits the process: code 1 for an HTTP error, a malformed response, or a
usage error, and code 2 when the server could not be reached at all.
"""

import json
import sys
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, NoReturn

import httpx2 as httpx
from rich.markup import escape

import hassette.cli.output as cli_output
from hassette.cli.target import (
    CLI_AUTH_TOKEN_ENV,
    SOURCE_CLI_TOKEN_FILE,
    SOURCE_TOKEN_FILE_FLAG,
    credential_source_names,
)

EXIT_FAILURE = 1
"""Exit code for an HTTP error, a malformed response, or a usage error."""

EXIT_NETWORK_ERROR = 2
"""Exit code when the server could not be reached at all."""

CLI_AUTH_DOCS_URL = "https://hassette.readthedocs.io/en/stable/pages/cli/configuration/#web-api-token"
"""Where an operator hitting a 401 goes next. The web API credential is a separate concept from
the Home Assistant long-lived token, and nothing in a 401 hints that a second token even exists
unless the message says so."""

CLI_AUTH_REMEDIES = f"{SOURCE_TOKEN_FILE_FLAG}, {SOURCE_CLI_TOKEN_FILE}, or {CLI_AUTH_TOKEN_ENV}"
"""The credential-supplying knobs that apply to any target, loopback or not.

Built from the same identifiers the resolvers use so a renamed setting cannot leave this
remedy naming a knob that no longer exists."""


@dataclass(frozen=True)
class ErrorContext:
    """Everything the error renderers need to know about one CLI invocation's target.

    Attributes:
        json_mode: Write errors as a JSON document on stdout instead of Rich text on stderr.
        debug_mode: Include the request URL, method, and response body in error output.
        display_url: The target URL as shown to the operator.
        is_loopback: The target is on this machine; suppresses the ``Target:`` line.
        insecure_from_config: TLS verification is off because of ``cli.verify_ssl`` in config,
            not an explicit flag on this invocation — a silent, durable opt-out worth warning about.
        credential_source_label: Where the attached credential came from, or ``None`` when no
            credential was attached.
    """

    json_mode: bool
    debug_mode: bool
    display_url: str
    is_loopback: bool
    insecure_from_config: bool
    credential_source_label: str | None

    def print_tls_warning(self) -> None:
        """Print the "TLS verification is disabled" warning for the current ``display_url``."""
        cli_output.stderr_console.print(
            f"[bold yellow]Warning:[/bold yellow] TLS verification is disabled for {self.display_url} "
            "(cli.verify_ssl = false in config).",
            highlight=False,
        )

    def auth_failure_hint(self) -> str:
        """Explain a 401 in terms of the credential this invocation actually sent.

        A 401 with no context leaves three different failures looking identical: no credential
        exists, a credential exists but belongs to a *different* instance, or the target is
        simply not running yet. Naming the resolved source separates them — in particular the
        loopback case where the CLI attached this machine's own instance token to a request
        aimed at a second instance on the same host, which is indistinguishable from a plain
        bad token unless the message says where the value came from.

        Three branches, in the order they are tested:

        - a credential resolved: names the source and says it was rejected
        - none resolved, loopback: lists the chain that came up empty, then asks whether
          hassette has been started
        - none resolved, remote: explains why server-scoped sources were withheld

        Returns:
            The parenthetical appended to the server's own 401 detail.
        """
        if self.credential_source_label is not None:
            # Deliberately not split by loopback/remote the way the no-credential cases are: the
            # remedy is the same either way. The proxy clause is remote-only on noise grounds,
            # not because loopback rules a proxy out — a local forward-auth gateway on a
            # loopback port is possible, but it is rare next to the dominant local case (a
            # stale or wrong instance token), and the sentence above stays true either way
            # since it never claims Hassette itself was the rejecter.
            # Joined rather than concatenated so the spacing between clauses is visible in the
            # source: with += the correct output depends on every fragment carrying a trailing
            # space, which nothing in the code signals and a formatter could silently strip.
            sentences = [
                f"the credential sent came from {self.credential_source_label}, and it was rejected.",
                f"Point the CLI at the target's own credential with {CLI_AUTH_REMEDIES}.",
            ]
            if not self.is_loopback:
                sentences.append(
                    "If this target sits behind a forward-auth proxy, the proxy may be rejecting "
                    "the request before it reaches Hassette."
                )
            sentences.append(f"See {CLI_AUTH_DOCS_URL}")
            return " ".join(sentences)
        if self.is_loopback:
            # Nothing resolved — distinguish this from "token was wrong" so the operator isn't
            # left guessing why an unauthenticated request failed. Phrased as an outcome rather
            # than a claim about configuration: a configured cli.token_file that is missing,
            # unreadable, or empty falls through to the next source silently, so "unset" and
            # "configured but unusable" are indistinguishable from here.
            return (
                "no credential was attached — nothing in the credential chain resolved to a usable "
                f"value ({credential_source_names()}). If one of those is configured, check that the "
                "file exists, is readable, and is not empty; otherwise, has hassette been started? "
                f"Attach one with {CLI_AUTH_REMEDIES}. See {CLI_AUTH_DOCS_URL}"
            )
        # A server-scoped credential source was suppressed for this remote target —
        # separate the remedies by where they apply, since one is local (attach a
        # credential) and the other is remote (reconfigure the instance being queried).
        return (
            "no credential was attached to this remote request — server-scoped sources "
            f"({credential_source_names(scope='server')}) describe this machine's instance "
            f"and are never sent to a remote target. Attach one locally with {CLI_AUTH_REMEDIES} — or, "
            "if this target sits behind a forward-auth proxy, configure trusted_proxies on the "
            "remote instance, which requires access to that host and a restart. "
            f"See {CLI_AUTH_DOCS_URL}"
        )

    def handle_http_error(self, response: httpx.Response) -> NoReturn:
        """Print HTTP error and exit with code 1."""
        try:
            detail = response.json().get("detail", response.text)
        except (ValueError, AttributeError):
            detail = response.text

        if response.status_code == HTTPStatus.UNAUTHORIZED:
            detail = f"{detail} ({self.auth_failure_hint()})"
        elif 300 <= response.status_code < 400:
            detail = (
                f"{detail} (this response is a redirect — likely a forward-auth login page in "
                "front of the target, not Hassette itself. See the reverse-proxy section of the "
                "CLI configuration docs.)"
            )

        # escape(): detail carries a server-supplied body and, for a 401, the resolved
        # credential source — which can be a filesystem path. Rich parses square brackets as
        # markup, so an unescaped "[/bold]" in either one raises MarkupError instead of
        # printing the error the operator needs.
        self.render_response_error(
            response,
            str(detail),
            heading=f"[bold red]Error {response.status_code}:[/bold red] {escape(str(detail))}",
            body=response.text,
            heading_highlight=None,
        )

    def handle_malformed_response(self, response: httpx.Response, exc: Exception) -> NoReturn:
        """Print a clean error for a successful-status response whose body isn't usable.

        Reached when the HTTP status looked successful (2xx, or a tolerated 503) but the body
        is not valid JSON or doesn't match the expected model. Both point at the same root
        cause: the CLI isn't actually talking to a compatible hassette instance — wrong
        ``--server-url`` (a reverse proxy or unrelated service answering with a 200 HTML page)
        or CLI/server version skew. Exits like any other error path instead of letting the
        parse exception surface as a raw traceback.
        """
        if isinstance(exc, json.JSONDecodeError):
            reason = "the response body is not valid JSON"
        elif isinstance(exc, UnicodeDecodeError):
            reason = "the response body is not valid UTF-8"
        else:
            reason = f"the response body does not match the expected shape ({exc})"
        detail = (
            f"response from {response.url} is not a valid hassette API response — {reason}. "
            "Check --server-url and for CLI/server version skew."
        )

        # response.text re-triggers the same decode failure for a UnicodeDecodeError body, so the
        # debug body dump must not rely on it — decode leniently instead.
        # escape(): detail quotes the validation failure, which echoes the offending body value,
        # and the debug dump prints the body verbatim. Rich parses square brackets as markup, so
        # an unescaped closing tag in either raises MarkupError instead of printing the error.
        self.render_response_error(
            response,
            detail,
            heading=f"[bold red]Error:[/bold red] {escape(detail)}",
            body=response.content.decode("utf-8", errors="replace"),
            heading_highlight=False,
        )

    def render_response_error(
        self, response: httpx.Response, detail: str, *, heading: str, body: str, heading_highlight: bool | None
    ) -> NoReturn:
        """Render an error about a received response in the active output mode and exit with code 1.

        Shared by :meth:`handle_http_error` and :meth:`handle_malformed_response`, which differ only
        in the detail text, the human-mode heading, and how the debug body is decoded.
        ``heading_highlight`` is passed to Rich as-is: ``None`` defers to the console's setting.
        """
        target, tls_verified = self.target_and_tls()
        if self.json_mode:
            extra = (
                {"url": str(response.url), "method": response.request.method, "body": body} if self.debug_mode else None
            )
            _write_json_error(response.status_code, detail, debug_extra=extra, target=target, tls_verified=tls_verified)
        else:
            cli_output.stderr_console.print(heading, highlight=heading_highlight)
            if target is not None:
                cli_output.stderr_console.print(f"[dim]Target:[/dim] {target}", highlight=False)
            if tls_verified is False:
                self.print_tls_warning()
            if self.debug_mode:
                cli_output.stderr_console.print(f"  [dim]URL:[/dim]    {response.request.method} {response.url}")
                cli_output.stderr_console.print(f"  [dim]Body:[/dim]   {escape(body)}")
        sys.exit(EXIT_FAILURE)

    def handle_network_error(self, message: str) -> NoReturn:
        """Print a network error and exit with code 2."""
        target, tls_verified = self.target_and_tls()
        if self.json_mode:
            _write_json_error(None, message, target=target, tls_verified=tls_verified)
        else:
            cli_output.stderr_console.print(f"[bold red]Network error:[/bold red] {message}")
            if tls_verified is False:
                self.print_tls_warning()
        sys.exit(EXIT_NETWORK_ERROR)

    def target_and_tls(self) -> tuple[str | None, bool | None]:
        """Derive the JSON-error envelope's ``target``/``tls_verified`` fields.

        Shared by every handler so the loopback-suppression and config-vs-flag TLS logic has a
        single source of truth.
        """
        target = self.display_url if not self.is_loopback else None
        tls_verified = False if self.insecure_from_config else None
        return target, tls_verified


def emit_usage_error(message: str, *, json_mode: bool = False) -> NoReturn:
    """Print a usage error and exit non-zero.

    Module-level so callers with no live :class:`~hassette.cli.client.HassetteCLIClient` — like
    ``run``, which starts the server directly and never talks to it over HTTP — can format a usage
    error the same way :meth:`~hassette.cli.client.HassetteCLIClient.error_usage` does. ``run`` has
    no ``--json`` flag today and always calls this with the default ``json_mode=False``; once one is
    added, its command function can pass through ``ctx.json_mode`` to get full parity with every
    other command's ``--json`` handling.
    """
    if json_mode:
        _write_json_error(None, message)
    else:
        # escape(): a usage error interpolates values the operator controls — a --token-file
        # path, an --app key, an --instance name. Rich reads square brackets as markup, so an
        # unescaped "[/bold]" in any of them raises MarkupError instead of printing the error.
        cli_output.stderr_console.print(f"[bold red]Usage error:[/bold red] {escape(message)}", highlight=False)
    sys.exit(EXIT_FAILURE)


def _write_json_error(
    status: int | None,
    detail: str,
    debug_extra: dict[str, Any] | None = None,
    target: str | None = None,
    tls_verified: bool | None = None,
) -> None:
    """Write a JSON error document to stdout."""
    doc: dict[str, Any] = {"error": True, "status": status, "detail": detail}
    if target is not None:
        doc["target"] = target
    if tls_verified is not None:
        doc["tls_verified"] = tls_verified
    if debug_extra:
        doc["debug"] = debug_extra
    sys.stdout.write(json.dumps(doc) + "\n")
    sys.stdout.flush()

"""Base-href resolution and shell rendering for the SPA (design/specs/130-ingress-base-path)."""

import re
from pathlib import Path

import pytest
from starlette.datastructures import Headers

from hassette.web.auth.trusted_proxies import EMPTY_TRUSTED_PROXY_SET
from hassette.web.spa import (
    BASE_MARKER,
    FORWARDED_PREFIX_HEADER,
    INGRESS_PATH_HEADER,
    WARNED_PAIRS_CAP,
    BaseRejection,
    Rejected,
    SpaShell,
    load_spa_shell,
    resolve_base,
)
from tests.support.web_mocks import trusted_proxy_set

FRONTEND_PLUGIN = Path(__file__).parents[3] / "frontend" / "no-absolute-paths.ts"
"""Declares the TS half of the ``BASE_MARKER`` contract, which the build checks ``index.html`` against."""

PROXY = "172.30.32.2"
STRANGER = "203.0.113.9"
TRUSTED = trusted_proxy_set(PROXY)
INGRESS = "/api/hassio_ingress/abc_DEF-123"


def resolve(headers: dict[str, str], peer: str | None = PROXY, *, auth_enabled: bool = True) -> str | Rejected:
    return resolve_base(Headers(headers), peer, TRUSTED, auth_enabled=auth_enabled)


def resolve_raw(pairs: list[tuple[str, str]], peer: str | None = PROXY) -> str | Rejected:
    raw = [(name.lower().encode(), value.encode()) for name, value in pairs]
    return resolve_base(Headers(raw=raw), peer, TRUSTED, auth_enabled=True)


def write_build(spa_dir: Path, index: bytes) -> None:
    (spa_dir / "assets").mkdir()
    (spa_dir / "index.html").write_bytes(index)


class TestResolveBase:
    def test_no_header_is_root(self) -> None:
        assert resolve({}) == "/"

    def test_no_header_from_untrusted_peer_is_root(self) -> None:
        assert resolve({}, STRANGER) == "/"

    def test_ingress_path_gets_trailing_slash(self) -> None:
        assert resolve({INGRESS_PATH_HEADER: INGRESS}) == f"{INGRESS}/"

    @pytest.mark.parametrize("prefix", ["/hassette", "/a/b.c/d~e", "/x_y-z"])
    def test_forwarded_prefix(self, prefix: str) -> None:
        assert resolve({FORWARDED_PREFIX_HEADER: prefix}) == f"{prefix}/"

    def test_surrounding_whitespace_is_stripped_before_matching(self) -> None:
        assert resolve({FORWARDED_PREFIX_HEADER: " /hassette "}) == "/hassette/"

    def test_one_trailing_slash_is_stripped_before_matching(self) -> None:
        assert resolve({FORWARDED_PREFIX_HEADER: "/hassette/"}) == "/hassette/"

    def test_ingress_path_wins_over_forwarded_prefix(self) -> None:
        assert resolve({INGRESS_PATH_HEADER: INGRESS, FORWARDED_PREFIX_HEADER: "/evil"}) == f"{INGRESS}/"

    def test_invalid_ingress_path_does_not_fall_through(self) -> None:
        result = resolve({INGRESS_PATH_HEADER: "/not-ingress", FORWARDED_PREFIX_HEADER: "/hassette"})
        assert result == Rejected(BaseRejection.MALFORMED_VALUE, INGRESS_PATH_HEADER)

    @pytest.mark.parametrize("blank", ["", "   ", "/"])
    def test_blank_ingress_path_counts_as_absent(self, blank: str) -> None:
        assert resolve({INGRESS_PATH_HEADER: blank, FORWARDED_PREFIX_HEADER: "/hassette"}) == "/hassette/"

    @pytest.mark.parametrize("blank", ["", "   ", "/"])
    def test_blank_header_alone_is_root(self, blank: str) -> None:
        assert resolve({FORWARDED_PREFIX_HEADER: blank}, STRANGER, auth_enabled=False) == "/"

    @pytest.mark.parametrize(
        "value",
        [
            "hassette",  # no leading slash
            "//evil.example",  # protocol-relative
            "/a//b",  # empty segment
            "/hassette//",  # only one trailing slash is stripped
            "/a/../b",
            "/./a",
            "/.hidden",
            '/a"><script>',
            "/a b",
            "/café",
        ],
    )
    def test_malformed_forwarded_prefix(self, value: str) -> None:
        assert resolve({FORWARDED_PREFIX_HEADER: value}) == Rejected(
            BaseRejection.MALFORMED_VALUE, FORWARDED_PREFIX_HEADER
        )

    @pytest.mark.parametrize(
        "value", ["/api/hassio_ingress/", "/api/hassio_ingress/a/b", "/api/hassio_ingress/a.b", "/hassette"]
    )
    def test_malformed_ingress_path(self, value: str) -> None:
        assert resolve({INGRESS_PATH_HEADER: value}) == Rejected(BaseRejection.MALFORMED_VALUE, INGRESS_PATH_HEADER)

    def test_repeated_header_is_malformed(self) -> None:
        result = resolve_raw([(FORWARDED_PREFIX_HEADER, "/evil"), (FORWARDED_PREFIX_HEADER, "/hassette")])
        assert result == Rejected(BaseRejection.MALFORMED_VALUE, FORWARDED_PREFIX_HEADER)

    def test_repeated_header_from_untrusted_peer_is_untrusted(self) -> None:
        pairs = [(FORWARDED_PREFIX_HEADER, "/evil"), (FORWARDED_PREFIX_HEADER, "/hassette")]
        assert resolve_raw(pairs, STRANGER) == Rejected(BaseRejection.UNTRUSTED_PEER, FORWARDED_PREFIX_HEADER)

    def test_repeated_blank_header_counts_as_absent(self) -> None:
        assert resolve_raw([(FORWARDED_PREFIX_HEADER, ""), (FORWARDED_PREFIX_HEADER, "/")]) == "/"

    def test_untrusted_peer(self) -> None:
        assert resolve({INGRESS_PATH_HEADER: INGRESS}, STRANGER) == Rejected(
            BaseRejection.UNTRUSTED_PEER, INGRESS_PATH_HEADER
        )

    def test_missing_peer_is_untrusted(self) -> None:
        assert resolve({FORWARDED_PREFIX_HEADER: "/hassette"}, None) == Rejected(
            BaseRejection.UNTRUSTED_PEER, FORWARDED_PREFIX_HEADER
        )

    def test_untrusted_peer_wins_over_malformed_value(self) -> None:
        assert resolve({FORWARDED_PREFIX_HEADER: "//evil"}, STRANGER) == Rejected(
            BaseRejection.UNTRUSTED_PEER, FORWARDED_PREFIX_HEADER
        )

    def test_trust_inactive_wins_over_everything(self) -> None:
        assert resolve({FORWARDED_PREFIX_HEADER: "//evil"}, STRANGER, auth_enabled=False) == Rejected(
            BaseRejection.TRUST_INACTIVE, FORWARDED_PREFIX_HEADER
        )

    def test_trust_inactive_with_empty_trust_set(self) -> None:
        result = resolve_base(
            Headers({INGRESS_PATH_HEADER: INGRESS}), PROXY, EMPTY_TRUSTED_PROXY_SET, auth_enabled=False
        )
        assert result == Rejected(BaseRejection.TRUST_INACTIVE, INGRESS_PATH_HEADER)


class TestSpaShell:
    SHELL = f"<html><head><meta charset='UTF-8' />{BASE_MARKER}</head><body></body></html>"

    def test_substitutes_base(self) -> None:
        resp = SpaShell(self.SHELL).render(f"{INGRESS}/", PROXY)
        assert resp.status_code == 200
        assert f'<base href="{INGRESS}/" />' in bytes(resp.body).decode()
        assert BASE_MARKER not in bytes(resp.body).decode()

    def test_root_base_keeps_marker_value(self) -> None:
        assert BASE_MARKER in bytes(SpaShell(self.SHELL).render("/", PROXY).body).decode()

    @pytest.mark.parametrize("resolution", ["/", Rejected(BaseRejection.UNTRUSTED_PEER, INGRESS_PATH_HEADER)])
    def test_caching_headers(self, resolution: str | Rejected) -> None:
        resp = SpaShell(self.SHELL).render(resolution, PROXY)
        assert resp.headers["cache-control"] == "no-cache"
        assert resp.headers["vary"] == f"{INGRESS_PATH_HEADER}, {FORWARDED_PREFIX_HEADER}"
        assert "etag" not in resp.headers
        assert "last-modified" not in resp.headers

    @pytest.mark.parametrize("reason", list(BaseRejection))
    def test_rejection_serves_diagnostic_page(self, reason: BaseRejection) -> None:
        resp = SpaShell(self.SHELL).render(Rejected(reason, FORWARDED_PREFIX_HEADER), STRANGER)
        body = bytes(resp.body).decode()
        assert resp.status_code == 403
        assert FORWARDED_PREFIX_HEADER in body
        assert STRANGER not in body
        assert "<script" not in body
        assert "<link" not in body

    def test_remedy_names_the_setting(self) -> None:
        shell = SpaShell(self.SHELL)
        untrusted = shell.render(Rejected(BaseRejection.UNTRUSTED_PEER, INGRESS_PATH_HEADER), STRANGER)
        inactive = shell.render(Rejected(BaseRejection.TRUST_INACTIVE, INGRESS_PATH_HEADER), STRANGER)
        assert "web_api.trusted_proxies" in bytes(untrusted.body).decode()
        assert "web_api.auth_enabled" in bytes(inactive.body).decode()

    def test_each_reason_and_peer_is_warned_once(self) -> None:
        shell = SpaShell(self.SHELL)
        for _ in range(3):
            shell.render(Rejected(BaseRejection.UNTRUSTED_PEER, INGRESS_PATH_HEADER), STRANGER)
        assert shell.warned_pairs == {(BaseRejection.UNTRUSTED_PEER, STRANGER)}
        shell.render(Rejected(BaseRejection.UNTRUSTED_PEER, INGRESS_PATH_HEADER), PROXY)
        shell.render(Rejected(BaseRejection.MALFORMED_VALUE, INGRESS_PATH_HEADER), None)
        assert shell.warned_pairs == {
            (BaseRejection.UNTRUSTED_PEER, STRANGER),
            (BaseRejection.UNTRUSTED_PEER, PROXY),
            (BaseRejection.MALFORMED_VALUE, "unknown"),
        }

    def test_warned_pairs_are_capped(self) -> None:
        shell = SpaShell(self.SHELL)
        for i in range(WARNED_PAIRS_CAP + 5):
            shell.render(Rejected(BaseRejection.UNTRUSTED_PEER, INGRESS_PATH_HEADER), f"203.0.113.{i}")
        assert len(shell.warned_pairs) == WARNED_PAIRS_CAP


class TestLoadSpaShell:
    def test_loads_shell_with_marker(self, tmp_path: Path) -> None:
        write_build(tmp_path, f"<head>{BASE_MARKER}</head>".encode())
        shell = load_spa_shell(tmp_path)
        assert shell is not None
        assert BASE_MARKER in shell.template

    def test_missing_marker(self, tmp_path: Path) -> None:
        write_build(tmp_path, b"<head></head>")
        assert load_spa_shell(tmp_path) is None

    def test_missing_index(self, tmp_path: Path) -> None:
        (tmp_path / "assets").mkdir()
        assert load_spa_shell(tmp_path) is None

    def test_missing_assets_dir(self, tmp_path: Path) -> None:
        (tmp_path / "index.html").write_text(f"<head>{BASE_MARKER}</head>")
        assert load_spa_shell(tmp_path) is None

    def test_undecodable_index(self, tmp_path: Path) -> None:
        write_build(tmp_path, BASE_MARKER.encode() + b"\xff\xfe")
        assert load_spa_shell(tmp_path) is None


def test_base_marker_matches_the_frontend_build_check() -> None:
    match = re.search(r"export const BASE_MARKER = '(.+)';", FRONTEND_PLUGIN.read_text())
    assert match is not None
    assert match.group(1) == BASE_MARKER

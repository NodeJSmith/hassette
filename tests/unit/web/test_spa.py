"""Base-href resolution and shell rendering for the SPA (design/specs/130-ingress-base-path)."""

from pathlib import Path

import pytest
from starlette.datastructures import Headers

from hassette.web.auth.trusted_proxies import EMPTY_TRUSTED_PROXY_SET
from hassette.web.spa import (
    BASE_MARKER,
    FORWARDED_PREFIX_HEADER,
    INGRESS_PATH_HEADER,
    BaseRejection,
    Rejected,
    SpaShell,
    load_spa_shell,
    resolve_base,
)
from tests.support.web_mocks import trusted_proxy_set

PROXY = "172.30.32.2"
STRANGER = "203.0.113.9"
TRUSTED = trusted_proxy_set(PROXY)
INGRESS = "/api/hassio_ingress/abc_DEF-123"


def resolve(headers: dict[str, str], peer: str | None = PROXY, *, auth_enabled: bool = True) -> str | Rejected:
    return resolve_base(Headers(headers), peer, TRUSTED, auth_enabled=auth_enabled)


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
        assert f'<base href="{INGRESS}/" />' in resp.body.decode()
        assert BASE_MARKER not in resp.body.decode()

    def test_root_base_keeps_marker_value(self) -> None:
        assert BASE_MARKER in SpaShell(self.SHELL).render("/", PROXY).body.decode()

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
        body = resp.body.decode()
        assert resp.status_code == 403
        assert FORWARDED_PREFIX_HEADER in body
        assert STRANGER not in body
        assert "<script" not in body
        assert "<link" not in body

    def test_remedy_names_the_setting(self) -> None:
        shell = SpaShell(self.SHELL)
        untrusted = shell.render(Rejected(BaseRejection.UNTRUSTED_PEER, INGRESS_PATH_HEADER), STRANGER)
        inactive = shell.render(Rejected(BaseRejection.TRUST_INACTIVE, INGRESS_PATH_HEADER), STRANGER)
        assert "web_api.trusted_proxies" in untrusted.body.decode()
        assert "web_api.auth_enabled" in inactive.body.decode()

    def test_each_reason_is_warned_once(self) -> None:
        shell = SpaShell(self.SHELL)
        for _ in range(3):
            shell.render(Rejected(BaseRejection.UNTRUSTED_PEER, INGRESS_PATH_HEADER), STRANGER)
        assert shell.warned == {BaseRejection.UNTRUSTED_PEER}
        shell.render(Rejected(BaseRejection.MALFORMED_VALUE, INGRESS_PATH_HEADER), PROXY)
        assert shell.warned == {BaseRejection.UNTRUSTED_PEER, BaseRejection.MALFORMED_VALUE}


class TestLoadSpaShell:
    def test_loads_shell_with_marker(self, tmp_path: Path) -> None:
        (tmp_path / "index.html").write_text(f"<head>{BASE_MARKER}</head>")
        shell = load_spa_shell(tmp_path)
        assert shell is not None
        assert BASE_MARKER in shell.template

    def test_missing_marker(self, tmp_path: Path) -> None:
        (tmp_path / "index.html").write_text("<head></head>")
        assert load_spa_shell(tmp_path) is None

    def test_missing_index(self, tmp_path: Path) -> None:
        assert load_spa_shell(tmp_path) is None

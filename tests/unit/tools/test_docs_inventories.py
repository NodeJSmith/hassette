import importlib.util
import io
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[3] / "tools" / "docs" / "inventories.py"
_spec = importlib.util.spec_from_file_location("docs_inventories", MODULE_PATH)
assert _spec is not None
assert _spec.loader is not None
inventories = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inventories)

HEADER = b"# Sphinx inventory version 2\n"


@pytest.fixture
def upstream(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, bytes | Exception]:
    """Point the committed inventories at `tmp_path` and serve downloads from the returned dict, keyed by name.

    A name mapped to an exception raises it from `urlopen`, the way a 429 or timeout would.
    """
    monkeypatch.setattr(inventories, "INVENTORY_DIR", tmp_path)
    monkeypatch.setattr(inventories, "INVENTORIES", {"alpha": "https://alpha.test/", "beta": "https://beta.test/"})
    responses: dict[str, bytes | Exception] = {}

    def fake_urlopen(req: urllib.request.Request, timeout: float) -> io.BytesIO:
        assert timeout == inventories.DOWNLOAD_TIMEOUT_SECONDS
        name = req.full_url.removeprefix("https://").split(".", 1)[0]
        body = responses[name]
        if isinstance(body, Exception):
            raise body
        return io.BytesIO(body)

    monkeypatch.setattr(inventories.urllib.request, "urlopen", fake_urlopen)
    return responses


def commit(name: str, content: bytes) -> None:
    inventories.inventory_path(name).write_bytes(content)


def test_check_reports_nothing_when_every_copy_matches(
    upstream: dict[str, bytes | Exception], capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("alpha", "beta"):
        upstream[name] = HEADER + name.encode()
        commit(name, HEADER + name.encode())

    assert inventories.main(["--check"]) == 0
    assert capsys.readouterr().out.strip() == ""


def test_check_names_changed_and_missing_copies_without_writing(
    upstream: dict[str, bytes | Exception], capsys: pytest.CaptureFixture[str]
) -> None:
    upstream["alpha"] = HEADER + b"new"
    upstream["beta"] = HEADER + b"beta"
    commit("alpha", HEADER + b"old")

    assert inventories.main(["--check"]) == 0
    assert capsys.readouterr().out.split() == ["alpha", "beta"]
    assert inventories.inventory_path("alpha").read_bytes() == HEADER + b"old"
    assert not inventories.inventory_path("beta").exists()


@pytest.mark.parametrize(
    "failure",
    [
        urllib.error.HTTPError("https://alpha.test/objects.inv", 429, "Too Many Requests", Message(), None),
        b"<html>rate limited</html>",
    ],
    ids=["http-429", "not-an-inventory"],
)
def test_failed_download_is_skipped_not_reported_as_drift(
    upstream: dict[str, bytes | Exception], capsys: pytest.CaptureFixture[str], failure: bytes | Exception
) -> None:
    upstream["alpha"] = failure
    upstream["beta"] = HEADER + b"new"
    commit("alpha", HEADER + b"old")
    commit("beta", HEADER + b"old")

    assert inventories.main(["--check"]) == inventories.INCOMPLETE_CHECK_EXIT_CODE
    captured = capsys.readouterr()
    assert captured.out.split() == ["beta"]
    assert "::warning::Skipped the alpha inventory" in captured.err

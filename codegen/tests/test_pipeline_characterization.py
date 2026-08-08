"""End-to-end characterization test for ``run_pipeline``.

``run_pipeline`` (see ``pipeline.py``) blends six responsibilities in one ~180-line function:
domain discovery/rejection, override loading/validation, per-domain state and entity generation,
sensor-constants generation, the predicate-freshness drift guard, and manifest/summary
bookkeeping. Splitting it risks silently reordering its interleaved stderr diagnostics or
dropping one of the ``generated_files``/``skipped_domains``/``rejections`` bookkeeping updates
threaded through every stage.

This test pins the current behavior — the *relative order* of every diagnostic line, the exact
manifest contents, the summary line, and the exit code — for one scenario that exercises all six
responsibilities in a single run:

- a normal domain that generates both a state model and an entity wrapper (``widget``)
- a domain whose entity wrapper is rejected for an unsafe service name, but whose state model
  still generates (``badservice``)
- a domain whose extraction raises and is skipped entirely (``flaky``)
- a reserved domain name rejected before generation ever starts (``base``)
- a manually-discovered override domain with no upstream component directory (``myintegration``)
- an override that matches no discovered domain, to pin the validation-warning path
  (``ghostdomain``)
- a synthetic ``sensor`` component (not itself a discovered entity domain) whose ``const.py`` and
  ``__init__.py`` drive sensor-constants generation and the predicate-freshness guard
- a stale manifest entry that becomes an orphan once this run's generated set excludes it

A later decomposition of ``run_pipeline`` into named steps must leave this test's assertions
unchanged.

Real override files bundled in ``hassette_codegen/overrides/`` are bypassed by monkeypatching
``pipeline.load_overrides`` — this scenario's domain names deliberately collide with none of them,
but patching keeps the scenario independent of whatever overrides the project happens to ship.
"""

from pathlib import Path

import pytest

from hassette_codegen import pipeline
from hassette_codegen.extractors.properties import ExtractedProperty
from hassette_codegen.ha_source import HASource
from hassette_codegen.manifest import load_manifest, save_manifest
from hassette_codegen.overrides import DomainOverride

from .test_pipeline_guards import STATES, UNSAFE_SERVICE_YAML, make_ha_core

ENTITIES = Path("src/hassette/models/entities")
CONST = Path("src/hassette/const")

SAFE_SERVICE_YAML = "turn_on:\n  fields: {}\n"

# A non-string top-level key is valid YAML but not a valid service name: extract_services'
# unqualified `service_name.startswith(".")` check has no int/str guard, so this raises a real
# AttributeError instead of the yaml.YAMLError the parser already handles. Used to force a
# genuine extraction failure for the "flaky" domain below, without touching pipeline internals.
MALFORMED_SERVICE_YAML = "123:\n  fields: {}\n"

# The exact source segment `ast.get_source_segment` will extract for the FunctionDef below —
# `extract_numeric_state_expected_source` returns this verbatim, and the freshness guard compares
# it (stripped) against the committed snapshot.
NUMERIC_STATE_EXPECTED_SOURCE = (
    'def _numeric_state_expected(state: str) -> bool:\n    return state not in ("unknown", "unavailable")'
)

SENSOR_INIT_PY = f'''"""Synthetic HA sensor component for predicate freshness testing."""


{NUMERIC_STATE_EXPECTED_SOURCE}


class _Marker:
    pass
'''

SENSOR_CONST_PY = """class SensorDeviceClass:
    TEMPERATURE = "temperature"
    HUMIDITY = "humidity"


NON_NUMERIC_DEVICE_CLASSES = {SensorDeviceClass.TEMPERATURE}


class SensorStateClass:
    MEASUREMENT = "measurement"
"""


def assert_in_order(text: str, *markers: str) -> None:
    """Assert each marker appears in ``text``, in the given order, without needing exact equality.

    Substring search rather than full-text equality on purpose: the noise-free scenario built
    below is already deterministic, so this only needs to prove the *relative order* of the
    diagnostics that matter, not forbid any other line from existing.
    """
    cursor = 0
    for marker in markers:
        idx = text.find(marker, cursor)
        assert idx != -1, f"expected {marker!r} to appear at or after position {cursor} in:\n{text}"
        cursor = idx + len(marker)


@pytest.fixture
def scenario(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[HASource, Path]:
    """Build the full six-responsibility scenario described in the module docstring."""
    ha_source = make_ha_core(
        tmp_path / "core",
        ["base", "badservice", "flaky", "widget"],
        services={
            "badservice": UNSAFE_SERVICE_YAML,
            "flaky": MALFORMED_SERVICE_YAML,
            "widget": SAFE_SERVICE_YAML,
        },
    )

    # A manually-discovered domain: an empty component directory (no __init__.py, so ordinary
    # discovery never sees it) plus an override that supplies its properties directly.
    (ha_source.path / "homeassistant" / "components" / "myintegration").mkdir()

    # A synthetic sensor component: no CACHED_PROPERTIES_WITH_ATTR_ marker, so it is never a
    # discovered entity domain — it exists only to drive sensor-constants generation and the
    # predicate-freshness guard, both of which read straight from this path.
    sensor_dir = ha_source.path / "homeassistant" / "components" / "sensor"
    sensor_dir.mkdir()
    (sensor_dir / "__init__.py").write_text(SENSOR_INIT_PY, encoding="utf-8")
    (sensor_dir / "const.py").write_text(SENSOR_CONST_PY, encoding="utf-8")

    overrides = {
        "myintegration": DomainOverride(
            domain="myintegration",
            discovery="manual",
            state_base_class="StringBaseState",
            properties=[ExtractedProperty(name="value", python_type="str", has_default=True)],
        ),
        # Matches no discovered domain — pins the validate_overrides mismatch warning.
        "ghostdomain": DomainOverride(domain="ghostdomain"),
    }
    monkeypatch.setattr(pipeline, "load_overrides", lambda: overrides)

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "codegen" / "snapshots").mkdir(parents=True)
    (repo_root / "codegen" / "snapshots" / "numeric_state_expected.py.txt").write_text(
        NUMERIC_STATE_EXPECTED_SOURCE, encoding="utf-8"
    )

    # A stale manifest entry with no corresponding domain in this run — becomes an orphan.
    save_manifest(repo_root, {Path(STATES / "ghostfile.py")})

    return ha_source, repo_root


class TestRunPipelineCharacterization:
    def test_generate_run_pins_ordering_bookkeeping_and_exit_code(
        self, scenario: tuple[HASource, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        ha_source, repo_root = scenario

        exit_code = pipeline.run_pipeline(ha_source, repo_root, check_mode=False)
        err = capsys.readouterr().err

        assert exit_code == 0

        assert_in_order(
            err,
            "WARNING: Rejected domain 'base': reserved for hand-written files",
            "Discovered 4 entity domains (1 manual)",
            "WARNING: Override file for 'ghostdomain' does not match any discovered domain",
            "WARNING: Rejected badservice entity wrapper:",
            "WARNING: Failed to extract flaky: 'int' object has no attribute 'startswith'",
            "Orphaned files (no longer generated): src/hassette/models/states/ghostfile.py",
            "Summary: 3 domains generated, 1 skipped, 2 rejected, 1 orphans",
        )

        expected_manifest = {
            STATES / "badservice.py",
            STATES / "widget.py",
            STATES / "myintegration.py",
            STATES / "__init__.py",
            ENTITIES / "widget.py",
            ENTITIES / "__init__.py",
            CONST / "sensor.py",
        }
        assert load_manifest(repo_root) == expected_manifest, (
            "generated_files bookkeeping must match exactly — the manifest is what the next run's "
            "ownership and orphan checks consult"
        )

        assert not (repo_root / STATES / "flaky.py").exists()
        assert not (repo_root / ENTITIES / "badservice.py").exists()

    def test_check_run_pins_drift_free_pass_through_and_exit_code(
        self, scenario: tuple[HASource, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        ha_source, repo_root = scenario
        pipeline.run_pipeline(ha_source, repo_root, check_mode=False)
        capsys.readouterr()  # drop the generate run's output — only the check run is asserted on

        exit_code = pipeline.run_pipeline(ha_source, repo_root, check_mode=True)
        err = capsys.readouterr().err

        assert exit_code == 1

        assert_in_order(
            err,
            "WARNING: Rejected domain 'base': reserved for hand-written files",
            "Discovered 4 entity domains (1 manual)",
            "WARNING: Override file for 'ghostdomain' does not match any discovered domain",
            "WARNING: Rejected badservice entity wrapper:",
            "WARNING: Failed to extract flaky: 'int' object has no attribute 'startswith'",
            "Summary: 3 domains generated, 1 skipped, 2 rejected",
            "Skipped domains: flaky",
            "Rejected: base (domain name), badservice (entity wrapper)",
        )

        # A freshly-generated tree must be drift-free — every check_drift call (state models,
        # entity wrappers, sensor constants, both __init__.py files) and the predicate-freshness
        # guard all silently pass. Orphan detection is also write-mode-only.
        assert "is out of date" not in err
        assert "orphan" not in err.lower()

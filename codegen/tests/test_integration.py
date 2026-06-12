"""Integration tests — full pipeline against real HA core domains."""

import os
import py_compile
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from hassette_codegen.domain_data import ExtractedDomain
from hassette_codegen.extractors.base_class import determine_base_class
from hassette_codegen.extractors.constants import extract_sensor_constants
from hassette_codegen.extractors.features import extract_features
from hassette_codegen.extractors.properties import extract_properties
from hassette_codegen.extractors.services import extract_services
from hassette_codegen.generators.constants import generate_sensor_constants
from hassette_codegen.generators.entities import generate_entity_wrapper
from hassette_codegen.generators.states import generate_state_model
from hassette_codegen.ha_source import discover_domains
from hassette_codegen.overrides import get_override, load_overrides

_HA_CORE = Path(os.environ.get("HA_CORE_PATH", "~/source/core")).expanduser()
_HAS_HA_CORE = _HA_CORE.exists()
_COMPONENTS = _HA_CORE / "homeassistant" / "components"


def _extract_full_domain(domain_name: str) -> ExtractedDomain:
    """Extract everything for a domain — helper for integration tests."""
    component_dir = _COMPONENTS / domain_name
    init_py = component_dir / "__init__.py"
    overrides = load_overrides()

    return ExtractedDomain(
        name=domain_name,
        base_class=determine_base_class(init_py),
        properties=extract_properties(init_py),
        features=extract_features(component_dir),
        services=extract_services(component_dir),
        override=get_override(overrides, domain_name),
    )


@pytest.mark.skipif(not _HAS_HA_CORE, reason="HA core checkout not available")
class TestFanFullPipeline:
    def test_state_model_structure(self) -> None:
        domain = _extract_full_domain("fan")
        output = generate_state_model(domain)
        assert "class FanEntityFeature(IntFlag):" in output
        assert "SET_SPEED = 1" in output
        assert "class FanAttributes(AttributesBase):" in output
        assert "class FanState(BoolBaseState):" in output
        assert 'domain: Literal["fan"]' in output

    def test_state_model_has_supports_properties(self) -> None:
        domain = _extract_full_domain("fan")
        output = generate_state_model(domain)
        assert "supports_set_speed" in output
        assert "supports_oscillate" in output
        assert "supports_direction" in output

    def test_entity_wrapper_structure(self) -> None:
        domain = _extract_full_domain("fan")
        output = generate_entity_wrapper(domain)
        assert output is not None
        assert "class FanEntity(BaseEntity[FanState, str]):" in output
        assert "def turn_on(" in output
        assert "def turn_off(" in output
        assert "-> Coroutine[Any, Any, None]:" in output

    def test_state_model_compiles(self) -> None:
        domain = _extract_full_domain("fan")
        output = generate_state_model(domain)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(output)
            f.flush()
            py_compile.compile(f.name, doraise=True)

    def test_entity_wrapper_compiles(self) -> None:
        domain = _extract_full_domain("fan")
        output = generate_entity_wrapper(domain)
        assert output is not None
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(output)
            f.flush()
            py_compile.compile(f.name, doraise=True)


@pytest.mark.skipif(not _HAS_HA_CORE, reason="HA core checkout not available")
class TestLightFullPipeline:
    def test_intflag_in_state_file(self) -> None:
        domain = _extract_full_domain("light")
        output = generate_state_model(domain)
        assert "LightEntityFeature" in output
        assert "IntFlag" in output

    def test_entity_has_advanced_fields(self) -> None:
        domain = _extract_full_domain("light")
        output = generate_entity_wrapper(domain)
        assert output is not None
        assert "def turn_on(" in output
        assert "-> Coroutine[Any, Any, None]:" in output
        field_count = output.count("None,") + output.count("None)")
        assert field_count >= 5

    def test_color_override_applied(self) -> None:
        domain = _extract_full_domain("light")
        output = generate_entity_wrapper(domain)
        assert output is not None
        assert "Color" in output


@pytest.mark.skipif(not _HAS_HA_CORE, reason="HA core checkout not available")
class TestSensorFullPipeline:
    def test_state_model_uses_string_base(self) -> None:
        domain = _extract_full_domain("sensor")
        output = generate_state_model(domain)
        assert "class SensorState(StringBaseState):" in output

    def test_no_entity_wrapper(self) -> None:
        domain = _extract_full_domain("sensor")
        assert generate_entity_wrapper(domain) is None

    def test_constants_generated(self) -> None:
        constants = extract_sensor_constants(_HA_CORE)
        output = generate_sensor_constants(constants)
        assert "DEVICE_CLASS" in output
        assert "UNIT_OF_MEASUREMENT" in output
        assert "STATE_CLASS" in output
        assert "temperature" in output


@pytest.mark.skipif(not _HAS_HA_CORE, reason="HA core checkout not available")
class TestAllDomainsCompile:
    def test_all_state_models_compile(self) -> None:
        domains = discover_domains(_HA_CORE)
        overrides = load_overrides()
        failures: list[str] = []

        for domain_info in domains:
            try:
                init_py = domain_info.path / "__init__.py"
                extracted = ExtractedDomain(
                    name=domain_info.name,
                    base_class=determine_base_class(init_py),
                    properties=extract_properties(init_py),
                    features=extract_features(domain_info.path),
                    services=extract_services(domain_info.path) if domain_info.has_services_yaml else [],
                    override=get_override(overrides, domain_info.name),
                )
                output = generate_state_model(extracted)
                with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
                    f.write(output)
                    f.flush()
                    py_compile.compile(f.name, doraise=True)
            except Exception as exc:
                failures.append(f"{domain_info.name}: {exc}")

        assert not failures, "State model compilation failures:\n" + "\n".join(failures)


@pytest.mark.skipif(not _HAS_HA_CORE, reason="HA core checkout not available")
class TestPerformance:
    def test_all_domains_under_30_seconds(self) -> None:
        start = time.monotonic()
        domains = discover_domains(_HA_CORE)
        overrides = load_overrides()

        for domain_info in domains:
            init_py = domain_info.path / "__init__.py"
            extracted = ExtractedDomain(
                name=domain_info.name,
                base_class=determine_base_class(init_py),
                properties=extract_properties(init_py),
                features=extract_features(domain_info.path),
                services=extract_services(domain_info.path) if domain_info.has_services_yaml else [],
                override=get_override(overrides, domain_info.name),
            )
            generate_state_model(extracted)
            generate_entity_wrapper(extracted)

        elapsed = time.monotonic() - start
        assert elapsed < 30, f"Generation took {elapsed:.1f}s (target: <30s)"

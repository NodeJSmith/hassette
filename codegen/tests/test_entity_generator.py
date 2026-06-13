"""Unit tests for the entity wrapper generator."""

import ast
import py_compile
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from hassette_codegen.domain_data import ExtractedDomain
from hassette_codegen.extractors.services import ExtractedService, ServiceField
from hassette_codegen.generators.entities import generate_entity_wrapper
from hassette_codegen.overrides import DomainOverride


class TestEntityWrapperGenerator:
    def test_fan_entity(self) -> None:
        domain = ExtractedDomain(
            name="fan",
            base_class="BoolBaseState",
            services=[
                ExtractedService(
                    name="turn_on",
                    method_name="turn_on",
                    fields=[
                        ServiceField(name="percentage", selector_type="number", selector_data={"min": 0, "max": 100}),
                        ServiceField(name="preset_mode", selector_type="state", selector_data={}),
                    ],
                ),
                ExtractedService(name="turn_off", method_name="turn_off", fields=[]),
                ExtractedService(
                    name="set_percentage",
                    method_name="set_percentage",
                    fields=[
                        ServiceField(
                            name="percentage",
                            selector_type="number",
                            selector_data={"min": 0, "max": 100},
                            required=True,
                        ),
                    ],
                ),
            ],
        )
        output = generate_entity_wrapper(domain)
        assert output is not None
        assert "class FanEntity(BaseEntity[FanState, str]):" in output
        assert "def turn_on(" in output
        assert "def turn_off(" in output
        assert "def set_percentage(" in output
        assert "-> Coroutine[Any, Any, None]" in output
        assert "self.api.call_service(" in output
        assert "async def" not in output
        # The Coroutine[Any, Any, None] return annotation is evaluated at runtime (no future
        # annotations in this repo), so the names must be imported or the generated module
        # fails on import — which the substring checks above and py_compile would both miss.
        assert "from collections.abc import Coroutine" in output
        assert "from typing import Any" in output

    def test_all_params_keyword_only(self) -> None:
        domain = ExtractedDomain(
            name="fan",
            base_class="BoolBaseState",
            services=[
                ExtractedService(
                    name="turn_on",
                    method_name="turn_on",
                    fields=[ServiceField(name="pct", selector_type="number", selector_data={})],
                ),
            ],
        )
        output = generate_entity_wrapper(domain)
        assert output is not None
        assert "self,\n        *," in output

    def test_no_services_returns_none(self) -> None:
        domain = ExtractedDomain(name="sensor", base_class="NumericBaseState", services=[])
        assert generate_entity_wrapper(domain) is None

    def test_override_renames_applied(self) -> None:
        domain = ExtractedDomain(
            name="media_player",
            base_class="StringBaseState",
            services=[
                ExtractedService(
                    name="play_media",
                    method_name="play_media",
                    fields=[
                        ServiceField(name="media_content_type", selector_type="text", selector_data={}),
                    ],
                ),
            ],
            override=DomainOverride(
                domain="media_player",
                service_param_renames={"media_content_type": "media_type"},
            ),
        )
        output = generate_entity_wrapper(domain)
        assert output is not None
        assert "media_type" in output
        assert "media_content_type" not in output.split("call_service")[0]

    def test_output_compiles(self) -> None:
        domain = ExtractedDomain(
            name="fan",
            base_class="BoolBaseState",
            services=[
                ExtractedService(
                    name="turn_on",
                    method_name="turn_on",
                    fields=[ServiceField(name="pct", selector_type="number", selector_data={})],
                ),
            ],
        )
        output = generate_entity_wrapper(domain)
        assert output is not None
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(output)
            f.flush()
            py_compile.compile(f.name, doraise=True)

    def test_facade_class_emitted(self) -> None:
        domain = ExtractedDomain(
            name="fan",
            base_class="BoolBaseState",
            services=[
                ExtractedService(
                    name="turn_on",
                    method_name="turn_on",
                    fields=[ServiceField(name="pct", selector_type="number", selector_data={})],
                ),
                ExtractedService(name="turn_off", method_name="turn_off", fields=[]),
            ],
        )
        output = generate_entity_wrapper(domain)
        assert output is not None
        assert "class FanEntitySyncFacade(BaseEntitySyncFacade[FanState, str]):" in output

    def test_sync_property_override_emitted(self) -> None:
        domain = ExtractedDomain(
            name="fan",
            base_class="BoolBaseState",
            services=[
                ExtractedService(name="turn_off", method_name="turn_off", fields=[]),
            ],
        )
        output = generate_entity_wrapper(domain)
        assert output is not None
        assert 'def sync(self) -> "FanEntitySyncFacade":' in output
        # Caching is delegated to the base helper; no per-file construction or cast.
        assert "self._get_or_create_sync(FanEntitySyncFacade)" in output
        assert "cast(" not in output

    def test_facade_methods_match_async_signatures(self) -> None:
        domain = ExtractedDomain(
            name="cover",
            base_class="StringBaseState",
            services=[
                ExtractedService(name="open_cover", method_name="open_cover", fields=[]),
                ExtractedService(
                    name="set_cover_position",
                    method_name="set_cover_position",
                    fields=[
                        ServiceField(
                            name="position",
                            selector_type="number",
                            selector_data={"min": 0, "max": 100},
                            required=True,
                        ),
                    ],
                ),
            ],
        )
        output = generate_entity_wrapper(domain)
        assert output is not None
        # Facade class present
        assert "class CoverEntitySyncFacade(BaseEntitySyncFacade[CoverState, str]):" in output
        # No-param service emits a void method with just self
        assert "def open_cover(self) -> None:" in output
        # Required-param service emits keyword-only param
        assert "def set_cover_position(" in output
        assert "position:" in output
        # Facade delegates through self.entity.api.sync
        assert "self.entity.api.sync.call_service(" in output
        assert 'service="open_cover"' in output
        assert 'service="set_cover_position"' in output
        assert 'target={"entity_id": self.entity.entity_id}' in output

    def test_facade_methods_are_void(self) -> None:
        domain = ExtractedDomain(
            name="cover",
            base_class="StringBaseState",
            services=[
                ExtractedService(name="open_cover", method_name="open_cover", fields=[]),
                ExtractedService(
                    name="set_cover_position",
                    method_name="set_cover_position",
                    fields=[
                        ServiceField(
                            name="position",
                            selector_type="number",
                            selector_data={"min": 0, "max": 100},
                            required=True,
                        ),
                    ],
                ),
            ],
        )
        output = generate_entity_wrapper(domain)
        assert output is not None
        # Split on the facade class to inspect only the facade portion
        facade_portion = output.split("class CoverEntitySyncFacade", 1)[1]
        # Facade methods are synchronous and void: explicit `-> None`, no `return` of the
        # underlying ServiceResponse, and not a coroutine.
        assert "def open_cover(self) -> None:" in facade_portion
        assert "-> Coroutine" not in facade_portion
        assert "return self.entity.api.sync" not in facade_portion
        # Google-style docstring: fallback summary (no HA description in this synthetic domain),
        # no Returns section, no await/blocking warning.
        assert '"""Call the cover.open_cover service.' in facade_portion
        assert "Returns:" not in facade_portion
        assert "Must be awaited" not in facade_portion

    def test_facade_imports_base_facade_not_cast(self) -> None:
        domain = ExtractedDomain(
            name="fan",
            base_class="BoolBaseState",
            services=[
                ExtractedService(name="turn_off", method_name="turn_off", fields=[]),
            ],
        )
        output = generate_entity_wrapper(domain)
        assert output is not None
        # The base caching helper removed the per-file cast, so `cast` is no longer imported.
        assert "from typing import Any\n" in output
        assert "cast" not in output
        assert "BaseEntitySyncFacade" in output.split("class FanEntity")[0]

    def test_output_compiles_with_facade(self) -> None:
        domain = ExtractedDomain(
            name="cover",
            base_class="StringBaseState",
            services=[
                ExtractedService(name="open_cover", method_name="open_cover", fields=[]),
                ExtractedService(
                    name="set_cover_position",
                    method_name="set_cover_position",
                    fields=[
                        ServiceField(
                            name="position",
                            selector_type="number",
                            selector_data={"min": 0, "max": 100},
                            required=True,
                        ),
                    ],
                ),
            ],
        )
        output = generate_entity_wrapper(domain)
        assert output is not None
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(output)
            f.flush()
            py_compile.compile(f.name, doraise=True)

    def test_facade_param_lists_match_async_entity_methods(self) -> None:
        """Each facade method's parameter names mirror the async entity method's.

        String-presence checks would miss a template change that emits a parameter
        subset on the facade; this parses the AST and compares names directly.
        """
        domain = ExtractedDomain(
            name="cover",
            base_class="StringBaseState",
            services=[
                ExtractedService(name="open_cover", method_name="open_cover", fields=[]),
                ExtractedService(
                    name="set_cover_position",
                    method_name="set_cover_position",
                    fields=[
                        ServiceField(
                            name="position",
                            selector_type="number",
                            selector_data={"min": 0, "max": 100},
                            required=True,
                        ),
                    ],
                ),
            ],
        )
        output = generate_entity_wrapper(domain)
        assert output is not None
        tree = ast.parse(output)

        def method_params(class_name: str, method_name: str) -> list[str]:
            cls = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name), None)
            assert cls is not None, f"class {class_name} not found in generated output"
            fn = next((n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == method_name), None)
            assert fn is not None, f"method {method_name} not found on {class_name}"
            names = [a.arg for a in (fn.args.posonlyargs + fn.args.args + fn.args.kwonlyargs)]
            return [n for n in names if n != "self"]

        for method in ("open_cover", "set_cover_position"):
            async_params = method_params("CoverEntity", method)
            facade_params = method_params("CoverEntitySyncFacade", method)
            assert facade_params == async_params, (
                f"{method}: facade params {facade_params} != async entity params {async_params}"
            )

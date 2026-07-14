"""Unit tests for the entity wrapper generator."""

import ast
import py_compile
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from hassette_codegen.domain_data import ExtractedDomain
from hassette_codegen.extractors.features import ExtractedEnum
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

    def test_same_param_name_different_literals_get_distinct_aliases(self) -> None:
        # Two services share the param name "mode" but expose different Literal sets.
        # Keying the alias cache by param name alone would emit two `Mode = ...` lines,
        # the second overwriting the first and corrupting the earlier method's annotation.
        domain = ExtractedDomain(
            name="climate",
            base_class="StringBaseState",
            services=[
                ExtractedService(
                    name="set_hvac_mode",
                    method_name="set_hvac_mode",
                    fields=[
                        ServiceField(
                            name="mode",
                            selector_type="select",
                            selector_data={"options": ["heat", "cool"]},
                            required=True,
                        ),
                    ],
                ),
                ExtractedService(
                    name="set_fan_mode",
                    method_name="set_fan_mode",
                    fields=[
                        ServiceField(
                            name="mode",
                            selector_type="select",
                            selector_data={"options": ["low", "high"]},
                            required=True,
                        ),
                    ],
                ),
            ],
        )
        output = generate_entity_wrapper(domain)
        assert output is not None
        # Each Literal set gets its own alias, defined exactly once.
        assert output.count('ClimateMode = Literal["heat", "cool"]') == 1
        assert output.count('ClimateMode2 = Literal["low", "high"]') == 1
        # Both aliases are referenced — the first uses the bare name, the second the suffixed one.
        assert re.search(r"mode: ClimateMode\b", output)  # \b stops this matching "ClimateMode2"
        assert "mode: ClimateMode2" in output
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(output)
            f.flush()
            py_compile.compile(f.name, doraise=True)

    def test_shared_literal_reuses_single_alias(self) -> None:
        # The same Literal shape under the same param name should still collapse to one alias.
        domain = ExtractedDomain(
            name="climate",
            base_class="StringBaseState",
            services=[
                ExtractedService(
                    name="set_mode_a",
                    method_name="set_mode_a",
                    fields=[
                        ServiceField(
                            name="mode",
                            selector_type="select",
                            selector_data={"options": ["heat", "cool"]},
                            required=True,
                        ),
                    ],
                ),
                ExtractedService(
                    name="set_mode_b",
                    method_name="set_mode_b",
                    fields=[
                        ServiceField(
                            name="mode",
                            selector_type="select",
                            selector_data={"options": ["heat", "cool"]},
                            required=True,
                        ),
                    ],
                ),
            ],
        )
        output = generate_entity_wrapper(domain)
        assert output is not None
        assert output.count('ClimateMode = Literal["heat", "cool"]') == 1
        assert "ClimateMode2" not in output

    def test_multiple_selector_wraps_in_list(self) -> None:
        # A selector with multiple: true accepts a list of the base type.
        domain = ExtractedDomain(
            name="media_player",
            base_class="StringBaseState",
            services=[
                ExtractedService(
                    name="join",
                    method_name="join",
                    fields=[
                        ServiceField(
                            name="group_members",
                            selector_type="entity",
                            selector_data={"multiple": True, "domain": "media_player"},
                            required=True,
                        ),
                    ],
                ),
            ],
        )
        output = generate_entity_wrapper(domain)
        assert output is not None
        assert "group_members: list[str]" in output

    def test_multiple_select_aliases_inner_literal(self) -> None:
        # A multiple: true select yields list[Literal[...]]; the inner Literal should still be
        # promoted to a named alias and reused, not inlined alongside an aliased bare copy.
        domain = ExtractedDomain(
            name="todo",
            base_class="StringBaseState",
            services=[
                ExtractedService(
                    name="get_items",
                    method_name="get_items",
                    fields=[
                        ServiceField(
                            name="status",
                            selector_type="select",
                            selector_data={"options": ["needs_action", "completed"], "multiple": True},
                        ),
                    ],
                ),
                ExtractedService(
                    name="update_item",
                    method_name="update_item",
                    fields=[
                        ServiceField(
                            name="status",
                            selector_type="select",
                            selector_data={"options": ["needs_action", "completed"]},
                        ),
                    ],
                ),
            ],
        )
        output = generate_entity_wrapper(domain)
        assert output is not None
        # One alias definition, shared by the bare and the list-wrapped usage.
        assert output.count('TodoStatus = Literal["needs_action", "completed"]') == 1
        assert "status: list[TodoStatus] | None" in output
        assert "status: TodoStatus | None" in output
        assert "list[Literal[" not in output  # inner literal is aliased, not inlined

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


def _enum(name: str, *members: tuple[str, str]) -> ExtractedEnum:
    return ExtractedEnum(name=name, members=list(members), kind="StrEnum")


def _domain(
    name: str,
    strenums: list[ExtractedEnum],
    services: list[ExtractedService],
    override: DomainOverride | None = None,
) -> ExtractedDomain:
    return ExtractedDomain(
        name=name,
        base_class="StringBaseState",
        strenums=strenums,
        services=services,
        override=override,
    )


class TestStrEnumMatching:
    """StrEnum cross-referencing for service params (issue #718)."""

    def test_name_based_match_str_to_strenum(self) -> None:
        domain = _domain(
            "climate",
            strenums=[_enum("HVACMode", ("OFF", "off"), ("HEAT", "heat"), ("COOL", "cool"))],
            services=[
                ExtractedService(
                    name="set_hvac_mode",
                    method_name="set_hvac_mode",
                    fields=[
                        ServiceField(name="hvac_mode", selector_type="text", selector_data={}, required=True),
                    ],
                ),
            ],
        )
        output = generate_entity_wrapper(domain)
        assert output is not None
        assert "hvac_mode: HVACMode" in output
        assert "import ClimateAttributes, HVACMode" in output

    def test_value_based_match_literal_to_strenum(self) -> None:
        domain = _domain(
            "media_player",
            strenums=[_enum("RepeatMode", ("OFF", "off"), ("ALL", "all"), ("ONE", "one"))],
            services=[
                ExtractedService(
                    name="repeat_set",
                    method_name="repeat_set",
                    fields=[
                        ServiceField(
                            name="repeat",
                            selector_type="select",
                            selector_data={"options": ["off", "all", "one"]},
                            required=True,
                        ),
                    ],
                ),
            ],
        )
        output = generate_entity_wrapper(domain)
        assert output is not None
        assert "repeat: RepeatMode" in output
        assert "RepeatMode" in output.split("class")[0]
        # Literal alias should NOT be generated — StrEnum supersedes it
        assert "MediaPlayerRepeat = Literal" not in output

    def test_value_based_match_list_literal_to_strenum(self) -> None:
        domain = _domain(
            "todo",
            strenums=[_enum("TodoItemStatus", ("NEEDS_ACTION", "needs_action"), ("COMPLETED", "completed"))],
            services=[
                ExtractedService(
                    name="get_items",
                    method_name="get_items",
                    fields=[
                        ServiceField(
                            name="status",
                            selector_type="select",
                            selector_data={"options": ["needs_action", "completed"], "multiple": True},
                        ),
                    ],
                ),
            ],
        )
        output = generate_entity_wrapper(domain)
        assert output is not None
        assert "status: list[TodoItemStatus] | None" in output
        assert "TodoStatus = Literal" not in output

    def test_metadata_enums_excluded_from_matching(self) -> None:
        domain = _domain(
            "climate",
            strenums=[_enum("ClimateEntityStateAttribute", ("FAN_MODE", "fan_mode"), ("PRESET_MODE", "preset_mode"))],
            services=[
                ExtractedService(
                    name="set_fan_mode",
                    method_name="set_fan_mode",
                    fields=[
                        ServiceField(name="fan_mode", selector_type="text", selector_data={}, required=True),
                    ],
                ),
            ],
        )
        output = generate_entity_wrapper(domain)
        assert output is not None
        # Should remain str because ClimateEntityStateAttribute ends with "Attribute"
        assert "fan_mode: str" in output

    def test_param_type_override_wins_over_enum_match(self) -> None:
        domain = _domain(
            "climate",
            strenums=[_enum("HVACMode", ("OFF", "off"), ("HEAT", "heat"))],
            services=[
                ExtractedService(
                    name="set_hvac_mode",
                    method_name="set_hvac_mode",
                    fields=[
                        ServiceField(name="hvac_mode", selector_type="text", selector_data={}, required=True),
                    ],
                ),
            ],
            override=DomainOverride(
                domain="climate",
                param_type_overrides={"hvac_mode": "str"},
            ),
        )
        output = generate_entity_wrapper(domain)
        assert output is not None
        assert "hvac_mode: str" in output
        assert "HVACMode" not in output

    def test_optional_enum_param_gets_none_union(self) -> None:
        domain = _domain(
            "climate",
            strenums=[_enum("HVACMode", ("OFF", "off"), ("HEAT", "heat"))],
            services=[
                ExtractedService(
                    name="set_hvac_mode",
                    method_name="set_hvac_mode",
                    fields=[
                        ServiceField(name="hvac_mode", selector_type="text", selector_data={}, required=False),
                    ],
                ),
            ],
        )
        output = generate_entity_wrapper(domain)
        assert output is not None
        assert "hvac_mode: HVACMode | None" in output

    def test_enum_match_with_renamed_param(self) -> None:
        domain = _domain(
            "media_player",
            strenums=[_enum("MediaType", ("MUSIC", "music"), ("TVSHOW", "tvshow"))],
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
        # Renamed param "media_type" should match StrEnum "MediaType"
        assert "media_type: MediaType | None" in output

    def test_collision_renamed_enum_uses_value_suffix(self) -> None:
        """StrEnums renamed by the state generator (name collides with Pydantic class) use the renamed name."""
        domain = _domain(
            "scene",
            strenums=[_enum("SceneState", ("ACTIVE", "active"), ("INACTIVE", "inactive"))],
            services=[
                ExtractedService(
                    name="activate",
                    method_name="activate",
                    fields=[
                        ServiceField(
                            name="scene_state",
                            selector_type="select",
                            selector_data={"options": ["active", "inactive"]},
                            required=True,
                        ),
                    ],
                ),
            ],
        )
        output = generate_entity_wrapper(domain)
        assert output is not None
        # The state generator renames SceneState → SceneStateValue to avoid collision
        assert "SceneStateValue" in output
        assert "import SceneAttributes, SceneStateValue" in output

    def test_output_compiles_with_enum_imports(self) -> None:
        domain = _domain(
            "climate",
            strenums=[_enum("HVACMode", ("OFF", "off"), ("HEAT", "heat"))],
            services=[
                ExtractedService(
                    name="set_hvac_mode",
                    method_name="set_hvac_mode",
                    fields=[
                        ServiceField(name="hvac_mode", selector_type="text", selector_data={}, required=True),
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

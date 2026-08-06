"""Unit tests for the shared config view builder (schema deref + type-driven masking)."""

import json
from typing import Annotated, Literal

from pydantic import BaseModel, Field, SecretStr, StringConstraints

from hassette.web.config_view import MASK_SENTINEL, build_config_view, deref_schema, mask_all_values, mask_values


class _PlainConfig(BaseModel):
    """Throwaway model: one SecretStr field, one plain str field."""

    real_secret: SecretStr
    plain_field: str


class _SecretSoundingButPlainConfig(BaseModel):
    """Throwaway model: fields with secret-sounding names but plain str type."""

    token: str
    api_key: str
    real_secret: SecretStr


class _InnerConfig(BaseModel):
    """Throwaway nested model for recursion tests."""

    nested_secret: SecretStr
    nested_name: str


class _OuterConfig(BaseModel):
    """Throwaway outer model for nested-object tests."""

    name: str
    inner: _InnerConfig
    top_secret: SecretStr | None = None


class _OptionalSecretConfig(BaseModel):
    """Throwaway model for unset-secret tests."""

    maybe_secret: SecretStr | None = None
    required_secret: SecretStr


class _OptionalGroupConfig(BaseModel):
    """Throwaway outer model with an OPTIONAL nested group (anyOf object branch).

    An optional nested model is emitted as ``anyOf: [{type: object, ...}, {type: null}]``
    with no top-level ``type``, so masking must look inside the anyOf branch to reach a
    secret nested at depth.
    """

    name: str
    inner_opt: _InnerConfig | None = None


class _ContainerSecretConfig(BaseModel):
    """Throwaway model: secrets held directly inside list/tuple/dict containers.

    Pydantic emits a different schema key for each: ``items`` for a homogeneous list,
    ``prefixItems`` for a fixed-length tuple, and ``additionalProperties`` for a mapping.
    The optional tuple additionally wraps its array shape in ``anyOf``.
    """

    key_list: list[SecretStr]
    key_pair: tuple[SecretStr, SecretStr] | None = None
    key_map: dict[str, SecretStr]


class _NestedContainerConfig(BaseModel):
    """Throwaway model: containers whose elements are objects or further containers.

    ``inners`` puts an object node under ``items``, so masking has to cross from a
    container back into a property walk. ``grouped_keys`` stacks two container levels.
    """

    inners: list[_InnerConfig]
    grouped_keys: dict[str, list[SecretStr]]


class _PlainContainerConfig(BaseModel):
    """Throwaway model: containers of plain values, which must stay visible."""

    names: list[str]
    labels: dict[str, str]
    real_secret: SecretStr


_PatternKey = Annotated[str, StringConstraints(pattern="^svc_")]


class _PatternMapConfig(BaseModel):
    """Throwaway model: a mapping whose key type carries a pattern constraint.

    Pydantic then emits the value schema under ``patternProperties`` keyed by the regex,
    not under ``additionalProperties`` — a fourth container key, distinct from the three
    that plain containers use.
    """

    creds: dict[_PatternKey, SecretStr] = {}


class _PlainVariant(BaseModel):
    """Discriminated-union variant carrying no secret."""

    kind: Literal["plain"] = "plain"
    label: str = "x"


class _SecretVariant(BaseModel):
    """Discriminated-union variant carrying a secret."""

    kind: Literal["secret"] = "secret"
    token: SecretStr


class _DiscriminatedListConfig(BaseModel):
    """Throwaway model: a list whose element is a discriminated union.

    Pydantic emits ``oneOf`` with one object branch per variant. Masking against only the
    first matching branch leaves a later variant's secret in plaintext, because the secret's
    key is simply absent from the earlier branch's ``properties``.
    """

    entries: list[Annotated[_PlainVariant | _SecretVariant, Field(discriminator="kind")]] = []


class TestTypeDrivenMasking:
    """Masking is driven by the schema's writeOnly/format:password markers, not field names."""

    def test_secret_str_field_is_masked(self) -> None:
        """A SecretStr field is replaced with the mask sentinel when set."""
        schema = _PlainConfig.model_json_schema()
        values = {"real_secret": "hunter2", "plain_field": "visible"}
        result = build_config_view(schema, values)
        assert result["config_values"]["real_secret"] == MASK_SENTINEL

    def test_plain_str_field_is_not_masked(self) -> None:
        """A plain str field is left unmasked even if its name sounds like a secret."""
        schema = _SecretSoundingButPlainConfig.model_json_schema()
        values = {"token": "plaintext-token", "api_key": "plaintext-key", "real_secret": "hunter2"}
        result = build_config_view(schema, values)
        assert result["config_values"]["token"] == "plaintext-token"
        assert result["config_values"]["api_key"] == "plaintext-key"
        assert result["config_values"]["real_secret"] == MASK_SENTINEL

    def test_type_driven_not_name_driven(self) -> None:
        """Fields named like secrets (token, api_key) stay unmasked when typed str; the
        SecretStr field is masked regardless of its name.
        """
        schema = _SecretSoundingButPlainConfig.model_json_schema()
        values = {"token": "t", "api_key": "k", "real_secret": "s"}
        result = build_config_view(schema, values)
        masked_keys = {k for k, v in result["config_values"].items() if v == MASK_SENTINEL}
        assert masked_keys == {"real_secret"}


class TestMaskingInputSources:
    """Masking works on both a live model_dump and a raw dict (e.g. TOML app config)."""

    def test_masking_on_model_dump(self) -> None:
        """Masking applied to model_dump(mode='json') output still results in masked sentinel.

        Pydantic natively renders SecretStr as '**********' in model_dump. Our schema-driven
        mask replaces that with MASK_SENTINEL — the value is masked either way.
        """
        schema = _PlainConfig.model_json_schema()
        obj = _PlainConfig(real_secret="hunter2", plain_field="visible")
        values = obj.model_dump(mode="json")
        # Pydantic has already masked it: values["real_secret"] == "**********"
        assert values["real_secret"] == "**********"
        result = build_config_view(schema, values)
        # Our mask replaces the Pydantic mask with MASK_SENTINEL
        assert result["config_values"]["real_secret"] == MASK_SENTINEL
        assert result["config_values"]["plain_field"] == "visible"

    def test_masking_on_raw_dict(self) -> None:
        """Masking applied directly to a raw dict (plaintext values) masks the secret field."""
        schema = _PlainConfig.model_json_schema()
        raw_values = {"real_secret": "hunter2", "plain_field": "visible"}
        result = build_config_view(schema, raw_values)
        assert result["config_values"]["real_secret"] == MASK_SENTINEL
        assert result["config_values"]["plain_field"] == "visible"


class TestNestedMasking:
    """Masking recurses into nested objects so deeply-nested SecretStr fields are masked."""

    def test_nested_secret_masked_in_model_dump(self) -> None:
        """A SecretStr nested inside a group is masked when values come from model_dump."""
        schema = _OuterConfig.model_json_schema()
        obj = _OuterConfig(name="test", inner=_InnerConfig(nested_secret="deep-secret", nested_name="lbl"))
        values = obj.model_dump(mode="json")
        result = build_config_view(schema, values)
        assert result["config_values"]["inner"]["nested_secret"] == MASK_SENTINEL
        assert result["config_values"]["inner"]["nested_name"] == "lbl"
        assert result["config_values"]["name"] == "test"

    def test_nested_secret_masked_in_raw_dict(self) -> None:
        """A SecretStr nested inside a group is masked when values come from a raw dict."""
        schema = _OuterConfig.model_json_schema()
        raw_values = {
            "name": "test",
            "inner": {"nested_secret": "deep-secret", "nested_name": "lbl"},
            "top_secret": None,
        }
        result = build_config_view(schema, raw_values)
        assert result["config_values"]["inner"]["nested_secret"] == MASK_SENTINEL
        assert result["config_values"]["inner"]["nested_name"] == "lbl"

    def test_top_level_optional_secret_masked(self) -> None:
        """A SecretStr | None field (anyOf schema) is masked when set."""
        schema = _OuterConfig.model_json_schema()
        values = {
            "name": "test",
            "inner": {"nested_secret": "s", "nested_name": "n"},
            "top_secret": "tok",
        }
        result = build_config_view(schema, values)
        assert result["config_values"]["top_secret"] == MASK_SENTINEL

    def test_secret_in_optional_nested_group_masked(self) -> None:
        """A SecretStr inside an OPTIONAL nested group (anyOf object branch) is masked.

        Without descending into the anyOf object branch, the secret would pass through
        as plaintext — a leak on the single masking gate.
        """
        schema = _OptionalGroupConfig.model_json_schema()
        values = {"name": "test", "inner_opt": {"nested_secret": "deep-secret", "nested_name": "lbl"}}
        result = build_config_view(schema, values)
        assert result["config_values"]["inner_opt"]["nested_secret"] == MASK_SENTINEL
        assert result["config_values"]["inner_opt"]["nested_name"] == "lbl"

    def test_optional_nested_group_unset_left_as_null(self) -> None:
        """An unset optional nested group stays None — recursion is skipped, no error."""
        schema = _OptionalGroupConfig.model_json_schema()
        values = {"name": "test", "inner_opt": None}
        result = build_config_view(schema, values)
        assert result["config_values"]["inner_opt"] is None


class TestContainerMasking:
    """Masking recurses through list/tuple/dict containers, not just object properties.

    Each case below covers a distinct schema key. A walk that only reads ``properties``
    hands the secret out in plaintext on the app-config endpoints, where values come from
    raw TOML and never passed through a ``SecretStr`` field for Pydantic to mask natively.
    """

    def test_list_of_secrets_masked(self) -> None:
        """Secrets under ``items`` (list[SecretStr]) are masked element-wise."""
        schema = _ContainerSecretConfig.model_json_schema()
        values = {"key_list": ["one", "two"], "key_map": {}}
        result = build_config_view(schema, values)
        assert result["config_values"]["key_list"] == [MASK_SENTINEL, MASK_SENTINEL]

    def test_optional_tuple_of_secrets_masked(self) -> None:
        """Secrets under ``prefixItems`` nested in ``anyOf`` are masked positionally.

        The field is optional, so Pydantic wraps the array shape in a union — container
        detection has to look inside union branches, not just at the top-level node.
        """
        schema = _ContainerSecretConfig.model_json_schema()
        values = {"key_list": [], "key_pair": ["left", "right"], "key_map": {}}
        result = build_config_view(schema, values)
        assert result["config_values"]["key_pair"] == [MASK_SENTINEL, MASK_SENTINEL]

    def test_runtime_tuple_masked_positionally(self) -> None:
        """A runtime tuple is masked like the list form, and stays a tuple.

        The endpoints only ever hand this function lists — TOML parsing and
        ``model_dump(mode="json")`` both produce lists — so this is not reachable through
        either route today. It is covered because ``prefixItems`` exists specifically to
        describe tuples: accepting one and returning it unmasked would be a silent leak the
        moment a caller passed ``model_dump(mode="python")`` output.
        """
        schema = _ContainerSecretConfig.model_json_schema()
        values = {"key_list": [], "key_pair": ("left", "right"), "key_map": {}}
        result = build_config_view(schema, values)
        assert result["config_values"]["key_pair"] == (MASK_SENTINEL, MASK_SENTINEL)

    def test_dict_of_secrets_masked(self) -> None:
        """Secrets under ``additionalProperties`` (dict[str, SecretStr]) are masked by value."""
        schema = _ContainerSecretConfig.model_json_schema()
        values = {"key_list": [], "key_map": {"prod": "live-key", "dev": "test-key"}}
        result = build_config_view(schema, values)
        assert result["config_values"]["key_map"] == {"prod": MASK_SENTINEL, "dev": MASK_SENTINEL}

    def test_dict_keys_are_preserved(self) -> None:
        """Mapping keys stay visible — only the values are secret."""
        schema = _ContainerSecretConfig.model_json_schema()
        values = {"key_list": [], "key_map": {"prod": "live-key", "dev": "test-key"}}
        result = build_config_view(schema, values)
        assert set(result["config_values"]["key_map"]) == {"prod", "dev"}

    def test_list_of_nested_models_masked(self) -> None:
        """A secret inside an object under ``items`` is masked; its siblings stay visible.

        This is the case a scalar-container-only fix would still miss: the element schema
        is an object with its own ``properties``, so the walk has to cross from container
        back into a property walk.
        """
        schema = _NestedContainerConfig.model_json_schema()
        values = {
            "inners": [
                {"nested_secret": "first", "nested_name": "a"},
                {"nested_secret": "second", "nested_name": "b"},
            ],
            "grouped_keys": {},
        }
        result = build_config_view(schema, values)
        assert [i["nested_secret"] for i in result["config_values"]["inners"]] == [MASK_SENTINEL, MASK_SENTINEL]
        assert [i["nested_name"] for i in result["config_values"]["inners"]] == ["a", "b"]

    def test_two_container_levels_masked(self) -> None:
        """dict[str, list[SecretStr]] — ``additionalProperties`` wrapping ``items``."""
        schema = _NestedContainerConfig.model_json_schema()
        values = {"inners": [], "grouped_keys": {"prod": ["a", "b"], "dev": ["c"]}}
        result = build_config_view(schema, values)
        assert result["config_values"]["grouped_keys"] == {
            "prod": [MASK_SENTINEL, MASK_SENTINEL],
            "dev": [MASK_SENTINEL],
        }

    def test_plain_containers_left_visible(self) -> None:
        """list[str] and dict[str, str] stay readable — masking is type-driven, not blanket.

        A regression to blanket-masking containers would break the config UI for every
        ordinary list or mapping setting.
        """
        schema = _PlainContainerConfig.model_json_schema()
        values = {
            "names": ["alpha", "beta"],
            "labels": {"env": "prod"},
            "real_secret": "hunter2",
        }
        result = build_config_view(schema, values)
        assert result["config_values"]["names"] == ["alpha", "beta"]
        assert result["config_values"]["labels"] == {"env": "prod"}
        assert result["config_values"]["real_secret"] == MASK_SENTINEL

    def test_empty_and_null_inside_containers_left_untouched(self) -> None:
        """The scalar rule carries into containers: '' and None are not masked."""
        schema = _ContainerSecretConfig.model_json_schema()
        values = {"key_list": ["", "set", None], "key_map": {"blank": "", "unset": None, "set": "x"}}
        result = build_config_view(schema, values)
        assert result["config_values"]["key_list"] == ["", MASK_SENTINEL, None]
        assert result["config_values"]["key_map"] == {"blank": "", "unset": None, "set": MASK_SENTINEL}

    def test_container_input_not_mutated(self) -> None:
        """Masking a container returns new containers; the caller's nested data is untouched."""
        schema = _NestedContainerConfig.model_json_schema()
        values = {
            "inners": [{"nested_secret": "deep", "nested_name": "a"}],
            "grouped_keys": {"prod": ["live-key"]},
        }
        build_config_view(schema, values)
        assert values["inners"][0]["nested_secret"] == "deep"
        assert values["grouped_keys"]["prod"] == ["live-key"]

    def test_masking_containers_is_idempotent(self) -> None:
        """Masking already-masked container values is a no-op.

        The global config path feeds in values Pydantic already masked, so the mask has to
        survive a second pass unchanged.
        """
        schema = _ContainerSecretConfig.model_json_schema()
        values = {"key_list": [MASK_SENTINEL], "key_map": {"prod": MASK_SENTINEL}}
        result = build_config_view(schema, values)
        assert result["config_values"]["key_list"] == [MASK_SENTINEL]
        assert result["config_values"]["key_map"] == {"prod": MASK_SENTINEL}


class TestPatternAndUnionMasking:
    """Two further container shapes that a first-match walk hands out in plaintext.

    Both were found by review after the initial container fix, and neither appears in the
    audit write-up. They share a root cause with it: the walk has to consider every schema
    key that can describe a value, and every union branch that can apply to it.
    """

    def test_pattern_properties_secrets_masked(self) -> None:
        """A secret under ``patternProperties`` is masked for a key matching the regex."""
        schema = _PatternMapConfig.model_json_schema()
        values = {"creds": {"svc_prod": "prod-plaintext"}}
        result = build_config_view(schema, values)
        assert result["config_values"]["creds"] == {"svc_prod": MASK_SENTINEL}

    def test_pattern_properties_non_matching_key_left_visible(self) -> None:
        """A key the pattern does not describe is not masked — still type-driven, not blanket."""
        schema = _PatternMapConfig.model_json_schema()
        values = {"creds": {"other": "not-a-secret-by-schema"}}
        result = build_config_view(schema, values)
        assert result["config_values"]["creds"] == {"other": "not-a-secret-by-schema"}

    def test_secret_in_later_union_branch_masked(self) -> None:
        """A secret on the second ``oneOf`` branch is masked, not just the first branch's fields.

        The element is a discriminated union. Returning after the first object branch that
        matches leaves ``token`` untouched, because ``token`` is absent from the plain
        variant's ``properties`` and therefore passes straight through.
        """
        schema = _DiscriminatedListConfig.model_json_schema()
        values = {"entries": [{"kind": "secret", "token": "union-plaintext"}]}
        result = build_config_view(schema, values)
        assert result["config_values"]["entries"][0]["token"] == MASK_SENTINEL

    def test_other_union_branch_plain_field_stays_visible(self) -> None:
        """Considering every branch must not blanket-mask a variant's plain fields."""
        schema = _DiscriminatedListConfig.model_json_schema()
        values = {"entries": [{"kind": "plain", "label": "visible"}]}
        result = build_config_view(schema, values)
        assert result["config_values"]["entries"][0]["label"] == "visible"
        assert result["config_values"]["entries"][0]["kind"] == "plain"


class TestUnsetSecrets:
    """An unset (null or absent) secret is left as-is, not replaced with the mask placeholder."""

    def test_null_secret_left_as_null(self) -> None:
        """A SecretStr | None field whose value is None stays None in the output."""
        schema = _OptionalSecretConfig.model_json_schema()
        values = {"maybe_secret": None, "required_secret": "s"}
        result = build_config_view(schema, values)
        assert result["config_values"]["maybe_secret"] is None
        assert result["config_values"]["required_secret"] == MASK_SENTINEL

    def test_empty_string_secret_left_as_empty(self) -> None:
        """A SecretStr field with an empty string value is left as empty, not masked."""
        schema = _PlainConfig.model_json_schema()
        values = {"real_secret": "", "plain_field": "visible"}
        result = build_config_view(schema, values)
        assert result["config_values"]["real_secret"] == ""

    def test_input_values_dict_not_mutated(self) -> None:
        """build_config_view returns a new dict; the caller's values dict is untouched."""
        schema = _OuterConfig.model_json_schema()
        values = {
            "name": "test",
            "inner": {"nested_secret": "deep-secret", "nested_name": "lbl"},
            "top_secret": "tok",
        }
        build_config_view(schema, values)
        # The original (including the nested dict) still holds the plaintext.
        assert values["top_secret"] == "tok"
        assert values["inner"]["nested_secret"] == "deep-secret"


class TestDeref:
    """build_config_view inlines all $ref/$defs so the output schema is self-contained."""

    def test_no_ref_in_schema_output(self) -> None:
        """After build_config_view, config_schema contains no $ref keys."""
        schema = _OuterConfig.model_json_schema()
        # Raw schema has $defs and $ref from the nested InnerConfig
        assert "$ref" in str(schema)

        result = build_config_view(schema, {"name": "x", "inner": {}, "top_secret": None})
        schema_json = json.dumps(result["config_schema"])
        assert "$ref" not in schema_json

    def test_no_defs_in_schema_output(self) -> None:
        """After build_config_view, config_schema contains no $defs keys."""
        schema = _OuterConfig.model_json_schema()
        assert "$defs" in schema

        result = build_config_view(schema, {"name": "x", "inner": {}, "top_secret": None})
        assert "$defs" not in result["config_schema"]

    def test_nested_model_inlined(self) -> None:
        """The nested model's properties are inlined directly under the property node."""
        schema = _OuterConfig.model_json_schema()
        result = build_config_view(schema, {"name": "x", "inner": {}, "top_secret": None})
        inner_prop = result["config_schema"]["properties"]["inner"]
        # Should have inlined Inner's properties, not a $ref
        assert "properties" in inner_prop
        assert "nested_secret" in inner_prop["properties"]


class TestDerefSchema:
    """deref_schema is the standalone deref step; build_config_view delegates to it."""

    def test_inlines_refs_and_drops_defs(self) -> None:
        """deref_schema resolves $ref nodes inline and removes the $defs store."""
        schema = _OuterConfig.model_json_schema()
        assert "$ref" in str(schema)
        assert "$defs" in schema

        result = deref_schema(schema)
        assert "$ref" not in json.dumps(result)
        assert "$defs" not in result
        assert "nested_secret" in result["properties"]["inner"]["properties"]

    def test_build_config_view_delegates_to_deref_schema(self) -> None:
        """build_config_view's config_schema is exactly what deref_schema produces."""
        schema = _OuterConfig.model_json_schema()
        values = {"name": "x", "inner": {}, "top_secret": None}
        assert build_config_view(schema, values)["config_schema"] == deref_schema(schema)

    def test_deref_once_then_mask_per_instance(self) -> None:
        """A schema deref'd once can mask multiple instances — the multi-instance app path."""
        deref = deref_schema(_PlainConfig.model_json_schema())
        props = deref["properties"]
        first = mask_values(props, {"real_secret": "a", "plain_field": "one"})
        second = mask_values(props, {"real_secret": "b", "plain_field": "two"})
        assert first["real_secret"] == MASK_SENTINEL
        assert second["real_secret"] == MASK_SENTINEL
        assert first["plain_field"] == "one"
        assert second["plain_field"] == "two"


class TestCyclicSchema:
    """A self-referential or cyclic JSON schema does not cause infinite recursion."""

    def test_cyclic_schema_returns(self) -> None:
        """build_config_view on a cyclic schema returns without raising RecursionError."""
        # A schema where Node.child references back to Node (JSON Schema self-reference)
        cyclic_schema = {
            "$defs": {
                "Node": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "child": {"$ref": "#/$defs/Node"},
                    },
                }
            },
            "type": "object",
            "properties": {
                "root": {"$ref": "#/$defs/Node"},
            },
        }
        values = {"root": {"name": "top", "child": {"name": "nested", "child": None}}}
        # Should return without RecursionError
        result = build_config_view(cyclic_schema, values)
        assert "config_schema" in result
        assert "config_values" in result


class TestMaskAllValues:
    """The schema-less safe floor masks every non-empty string at any depth."""

    def test_strings_masked_non_strings_preserved(self) -> None:
        values = {"password": "hunter2", "retries": 3, "enabled": True, "ratio": 1.5}
        result = mask_all_values(values)
        assert result["password"] == MASK_SENTINEL
        assert result["retries"] == 3
        assert result["enabled"] is True
        assert result["ratio"] == 1.5

    def test_nested_and_list_strings_masked(self) -> None:
        values = {"group": {"token": "secret"}, "items": ["a", 2, "b"]}
        result = mask_all_values(values)
        assert result["group"]["token"] == MASK_SENTINEL
        assert result["items"] == [MASK_SENTINEL, 2, MASK_SENTINEL]

    def test_empty_string_and_none_left_visible(self) -> None:
        values = {"empty": "", "missing": None}
        result = mask_all_values(values)
        assert result["empty"] == ""
        assert result["missing"] is None

    def test_does_not_mutate_input(self) -> None:
        values = {"password": "hunter2"}
        mask_all_values(values)
        assert values["password"] == "hunter2"

"""Unit tests for the shared config view builder (schema deref + type-driven masking)."""

import json

from pydantic import BaseModel, SecretStr

from hassette.web.config_view import MASK_SENTINEL, build_config_view


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
        SecretStr field is masked regardless of its name."""
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

"""Integration tests for GET /api/apps/{app_key}/config."""

import json
from typing import Any

from pydantic import BaseModel, SecretStr

from hassette.web.config_view import MASK_SENTINEL
from tests.integration.conftest import make_manifest_mock


class TestAppConfigEndpoint:
    """Tests for GET /api/apps/{app_key}/config."""

    async def test_known_app_returns_config(self, client, mock_hassette) -> None:
        """Returns 200 with AppConfigResponse for a known app key."""
        manifest = make_manifest_mock(
            app_key="my_app",
            filename="my_app.py",
            class_name="MyApp",
            enabled=True,
            app_config={"instance_name": "MyApp.0", "brightness": 100},
        )
        mock_hassette._app_handler.registry.get_manifest.return_value = manifest
        mock_hassette._app_handler.registry.get.return_value = _AppWithBasicConfig()

        response = await client.get("/api/apps/my_app/config")

        assert response.status_code == 200
        data = response.json()
        assert data["app_key"] == "my_app"
        assert data["filename"] == "my_app.py"
        assert data["class_name"] == "MyApp"
        assert data["enabled"] is True
        # Plain (non-secret) fields render unmasked through the schema-driven path.
        assert data["app_config"]["brightness"] == 100
        assert data["app_config"]["instance_name"] == "MyApp.0"

    async def test_unknown_app_returns_404(self, client, mock_hassette) -> None:
        """Returns 404 when app_key is not in the registry."""
        mock_hassette._app_handler.registry.get_manifest.return_value = None

        response = await client.get("/api/apps/nonexistent_app/config")

        assert response.status_code == 404

    async def test_multi_instance_app_returns_list_config(self, client, mock_hassette) -> None:
        """Returns list config for a multi-instance app."""
        list_config = [
            {"instance_name": "MyApp.0", "zone": "kitchen"},
            {"instance_name": "MyApp.1", "zone": "bedroom"},
        ]
        manifest = make_manifest_mock(
            app_key="my_app",
            class_name="MyApp",
            app_config=list_config,
        )
        mock_hassette._app_handler.registry.get_manifest.return_value = manifest
        mock_hassette._app_handler.registry.get.return_value = _AppWithBasicConfig()

        response = await client.get("/api/apps/my_app/config")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["app_config"], list)
        assert len(data["app_config"]) == 2
        assert data["app_config"][0]["zone"] == "kitchen"
        assert data["app_config"][1]["zone"] == "bedroom"

    async def test_disabled_app_secrets_masked_without_schema(self, client, mock_hassette) -> None:
        """A disabled app has no running instance and no loaded class, so no schema is
        available — every string value is masked as a safe floor so a secret never leaks."""
        manifest = make_manifest_mock(
            app_key="disabled_app",
            enabled=False,
            app_config={"password": "hunter2", "retries": 3},
        )
        mock_hassette._app_handler.registry.get_manifest.return_value = manifest
        # No live instance for a disabled app — this is the path the old code left unmasked.
        mock_hassette._app_handler.registry.get.return_value = None

        response = await client.get("/api/apps/disabled_app/config")

        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is False
        # The plaintext secret never reaches the wire — string values are masked.
        assert "hunter2" not in response.text
        assert data["app_config"]["password"] == MASK_SENTINEL
        # Non-string values (which can never be a secret) stay visible.
        assert data["app_config"]["retries"] == 3
        assert data["config_schema"] is None

    async def test_invalid_app_key_returns_400(self, client) -> None:
        """Invalid app_key format returns 400."""
        response = await client.get("/api/apps/!!invalid!!/config")

        assert response.status_code == 400

    async def test_framework_fields_returned(self, client, mock_hassette) -> None:
        """Response includes framework_fields listing base AppConfig + manifest fields."""
        manifest = make_manifest_mock(app_key="my_app", app_config={"brightness": 100})
        mock_hassette._app_handler.registry.get_manifest.return_value = manifest
        mock_hassette._app_handler.registry.get.return_value = _AppWithBasicConfig()

        response = await client.get("/api/apps/my_app/config")

        data = response.json()
        ff = data["framework_fields"]
        assert "instance_name" in ff
        assert "log_level" in ff
        assert "app_key" in ff
        assert "enabled" in ff
        assert "autostart" in ff
        assert "brightness" not in ff

    async def test_autostart_returned(self, client, mock_hassette) -> None:
        """Response includes autostart from the manifest."""
        manifest = make_manifest_mock(app_key="my_app", autostart=False, app_config={"brightness": 100})
        mock_hassette._app_handler.registry.get_manifest.return_value = manifest
        mock_hassette._app_handler.registry.get.return_value = _AppWithBasicConfig()

        response = await client.get("/api/apps/my_app/config")

        data = response.json()
        assert data["autostart"] is False

    async def test_manifest_fields_in_schema(self, client, mock_hassette) -> None:
        """Config schema includes enabled and autostart property definitions."""
        manifest = make_manifest_mock(app_key="my_app", app_config={"brightness": 100})
        mock_hassette._app_handler.registry.get_manifest.return_value = manifest
        mock_hassette._app_handler.registry.get.return_value = _AppWithBasicConfig()

        response = await client.get("/api/apps/my_app/config")

        schema = response.json()["config_schema"]
        props = schema["properties"]
        assert "enabled" in props
        assert props["enabled"]["type"] == "boolean"
        assert "autostart" in props
        assert props["autostart"]["type"] == "boolean"


def _has_ref(obj: Any) -> bool:
    """Return True if the object or any nested value contains a '$ref' key."""
    if isinstance(obj, dict):
        return "$ref" in obj or any(_has_ref(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_ref(v) for v in obj)
    return False


class _UnmaskedKeyConfig(BaseModel):
    """Stub app config: api_key is a plain str — schema says it is NOT a secret."""

    api_key: str = "default"


class _MaskedKeyConfig(BaseModel):
    """Stub app config: api_key is SecretStr — schema marks it writeOnly/password."""

    api_key: SecretStr


class _NestedGroup(BaseModel):
    """Nested sub-model that forces a $ref in the raw JSON schema."""

    host: str = "localhost"
    port: int = 8080


class _NestedAppConfig(BaseModel):
    """Stub app config with a nested model — raw schema has $defs/$ref."""

    connection: _NestedGroup = _NestedGroup()
    name: str = "default"


class _AppWithUnmaskedKey:
    app_config_cls = _UnmaskedKeyConfig


class _AppWithMaskedKey:
    app_config_cls = _MaskedKeyConfig


class _AppWithNested:
    app_config_cls = _NestedAppConfig


class _BasicAppConfig(BaseModel):
    """Stub app config with only plain (non-secret) fields — nothing should mask."""

    instance_name: str = ""
    brightness: int = 0
    zone: str = ""


class _AppWithBasicConfig:
    app_config_cls = _BasicAppConfig


class TestAppConfigTypeDrivenMasking:
    """Tests for type-driven masking on the app config endpoint.

    A field typed ``SecretStr`` is masked; a plain ``str`` field with
    a secret-sounding name is NOT masked. Masking is driven by the schema's
    writeOnly/format markers, never by field name.
    """

    async def test_untyped_str_field_renders_unmasked(self, client, mock_hassette) -> None:
        """api_key: str is NOT masked even though its name sounds like a secret.

        The old regex would mask this; the new schema-driven path must not.
        """
        manifest = make_manifest_mock(
            app_key="my_app",
            app_config={"api_key": "my-real-value"},
        )
        mock_hassette._app_handler.registry.get_manifest.return_value = manifest
        mock_hassette._app_handler.registry.get.return_value = _AppWithUnmaskedKey()

        response = await client.get("/api/apps/my_app/config")

        assert response.status_code == 200
        data = response.json()
        assert data["app_config"]["api_key"] == "my-real-value"

    async def test_secret_str_field_renders_masked(self, client, mock_hassette) -> None:
        """api_key: SecretStr IS masked — the schema marks it as a secret."""
        manifest = make_manifest_mock(
            app_key="my_app",
            app_config={"api_key": "plaintext-secret"},
        )
        mock_hassette._app_handler.registry.get_manifest.return_value = manifest
        mock_hassette._app_handler.registry.get.return_value = _AppWithMaskedKey()

        response = await client.get("/api/apps/my_app/config")

        assert response.status_code == 200
        data = response.json()
        assert data["app_config"]["api_key"] == MASK_SENTINEL

    async def test_plaintext_never_appears_for_secret_str_field(self, client, mock_hassette) -> None:
        """Plaintext of a SecretStr field must not appear anywhere in the response body."""
        manifest = make_manifest_mock(
            app_key="my_app",
            app_config={"api_key": "super-secret-value-12345"},
        )
        mock_hassette._app_handler.registry.get_manifest.return_value = manifest
        mock_hassette._app_handler.registry.get.return_value = _AppWithMaskedKey()

        response = await client.get("/api/apps/my_app/config")

        assert "super-secret-value-12345" not in response.text


class TestSchemaDeref:
    """Both config endpoints return schemas with all $refs resolved.

    The global endpoint uses field name ``config_values``; the app endpoint keeps
    its existing ``app_config`` field.  ``config_schema`` is the deref'd schema on
    both.
    """

    async def test_app_config_schema_has_no_ref(self, client, mock_hassette) -> None:
        """App config endpoint: config_schema is fully inlined (no $ref after deref)."""
        manifest = make_manifest_mock(
            app_key="my_app",
            app_config={"connection": {"host": "myhost", "port": 9090}, "name": "test"},
        )
        mock_hassette._app_handler.registry.get_manifest.return_value = manifest
        mock_hassette._app_handler.registry.get.return_value = _AppWithNested()

        response = await client.get("/api/apps/my_app/config")

        assert response.status_code == 200
        data = response.json()
        # config_schema must be fully inlined — the nested group schema is under connection.properties
        assert data["config_schema"] is not None
        assert not _has_ref(data["config_schema"]), (
            f"config_schema still contains $ref: {json.dumps(data['config_schema'], indent=2)}"
        )

    async def test_app_config_response_uses_app_config_field_not_config_values(self, client, mock_hassette) -> None:
        """App endpoint keeps app_config (not config_values) for the values field."""
        manifest = make_manifest_mock(
            app_key="my_app",
            app_config={"name": "test"},
        )
        mock_hassette._app_handler.registry.get_manifest.return_value = manifest
        mock_hassette._app_handler.registry.get.return_value = _AppWithNested()

        response = await client.get("/api/apps/my_app/config")

        data = response.json()
        assert "app_config" in data
        assert "config_values" not in data

    async def test_global_config_schema_has_no_ref(self, client) -> None:
        """Global config endpoint: config_schema is fully inlined (no $ref after deref)."""
        response = await client.get("/api/config")

        assert response.status_code == 200
        data = response.json()
        assert "config_schema" in data
        assert "config_values" in data
        assert not _has_ref(data["config_schema"]), (
            f"config_schema still contains $ref: {json.dumps(data['config_schema'], indent=2)}"
        )

    async def test_app_config_nested_group_inlined_in_schema(self, client, mock_hassette) -> None:
        """After deref, nested group properties are inlined directly under the property node."""
        manifest = make_manifest_mock(
            app_key="my_app",
            app_config={"connection": {"host": "h", "port": 1}, "name": "n"},
        )
        mock_hassette._app_handler.registry.get_manifest.return_value = manifest
        mock_hassette._app_handler.registry.get.return_value = _AppWithNested()

        response = await client.get("/api/apps/my_app/config")

        data = response.json()
        schema = data["config_schema"]
        assert schema is not None
        conn_prop = schema.get("properties", {}).get("connection", {})
        assert "properties" in conn_prop, f"connection schema not inlined: {conn_prop}"
        assert "host" in conn_prop["properties"]


class TestGlobalConfigManifestMasking:
    """Secret fields inside manifests' ``app_config`` are masked in the global config endpoint."""

    async def test_secret_str_field_renders_masked_in_manifest(self, client, mock_hassette) -> None:
        """A SecretStr field in a manifest's app_config is replaced by the mask sentinel."""
        mock_hassette.config.model_dump.return_value["apps"]["manifests"] = {
            "my_app": {
                "app_key": "my_app",
                "app_config": {"api_key": "plaintext-secret"},
            },
        }
        mock_hassette._app_handler.registry.get.return_value = _AppWithMaskedKey()

        response = await client.get("/api/config")

        manifests = response.json()["config_values"]["apps"]["manifests"]
        assert manifests["my_app"]["app_config"]["api_key"] == MASK_SENTINEL

    async def test_plain_str_field_renders_unmasked_in_manifest(self, client, mock_hassette) -> None:
        """A plain str field is NOT masked — masking is schema-driven, not name-driven."""
        mock_hassette.config.model_dump.return_value["apps"]["manifests"] = {
            "my_app": {
                "app_key": "my_app",
                "app_config": {"api_key": "my-real-value"},
            },
        }
        mock_hassette._app_handler.registry.get.return_value = _AppWithUnmaskedKey()

        response = await client.get("/api/config")

        manifests = response.json()["config_values"]["apps"]["manifests"]
        assert manifests["my_app"]["app_config"]["api_key"] == "my-real-value"

    async def test_safe_floor_when_no_schema(self, client, mock_hassette) -> None:
        """When no app class is available, every string value is masked as a safe floor."""
        mock_hassette.config.model_dump.return_value["apps"]["manifests"] = {
            "disabled_app": {
                "app_key": "disabled_app",
                "app_config": {"password": "hunter2", "retries": 3},
            },
        }
        mock_hassette._app_handler.registry.get.return_value = None
        mock_hassette.config.apps.manifests = {}

        response = await client.get("/api/config")

        app_config = response.json()["config_values"]["apps"]["manifests"]["disabled_app"]["app_config"]
        assert app_config["password"] == MASK_SENTINEL
        assert app_config["retries"] == 3

    async def test_plaintext_never_appears_in_response_body(self, client, mock_hassette) -> None:
        """Plaintext of a SecretStr field must not appear anywhere in the response body."""
        mock_hassette.config.model_dump.return_value["apps"]["manifests"] = {
            "my_app": {
                "app_key": "my_app",
                "app_config": {"api_key": "super-secret-value-12345"},
            },
        }
        mock_hassette._app_handler.registry.get.return_value = _AppWithMaskedKey()

        response = await client.get("/api/config")

        assert "super-secret-value-12345" not in response.text

    async def test_multi_instance_manifest_masked(self, client, mock_hassette) -> None:
        """Each instance in a multi-instance manifest has its secrets masked."""
        mock_hassette.config.model_dump.return_value["apps"]["manifests"] = {
            "my_app": {
                "app_key": "my_app",
                "app_config": [
                    {"instance_name": "MyApp.0", "api_key": "secret-0"},
                    {"instance_name": "MyApp.1", "api_key": "secret-1"},
                ],
            },
        }
        mock_hassette._app_handler.registry.get.return_value = _AppWithMaskedKey()

        response = await client.get("/api/config")

        app_config = response.json()["config_values"]["apps"]["manifests"]["my_app"]["app_config"]
        assert isinstance(app_config, list)
        assert app_config[0]["api_key"] == MASK_SENTINEL
        assert app_config[1]["api_key"] == MASK_SENTINEL
        assert app_config[0]["instance_name"] == "MyApp.0"

    async def test_no_manifests_passes_through(self, client) -> None:
        """When no manifests exist in config values, the response is unchanged."""
        response = await client.get("/api/config")

        assert response.status_code == 200
        data = response.json()
        assert "config_values" in data

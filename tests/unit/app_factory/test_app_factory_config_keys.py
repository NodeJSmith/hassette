"""AppFactory's accepted config keys and its warning for unrecognized ones."""

from unittest.mock import Mock

import pytest
from pydantic import AliasChoices, AliasPath, Field
from pydantic.alias_generators import to_camel
from pydantic_settings import SettingsConfigDict

from hassette import AppConfig
from hassette.core.app_factory import AppFactory, accepted_config_keys
from tests.support.outcomes import AnyIndexOutcomes

from .conftest import as_app_class, make_app_class


class MotionLightConfig(AppConfig):
    off_delay: int = 30


class AliasedDelayConfig(AppConfig):
    off_delay: int = Field(default=30, alias="delay")


class ByNameDelayConfig(AliasedDelayConfig):
    model_config = SettingsConfigDict(validate_by_name=True)


class ExplicitNoNameConfig(AliasedDelayConfig):
    model_config = SettingsConfigDict(populate_by_name=True, validate_by_name=False)


class OverrideOnlyConfig(AppConfig):
    log_level: str | None = "DEBUG"


class DelayMixin:
    off_delay: int = 30


class MixinOnlyConfig(DelayMixin, AppConfig):
    pass


class TrailingMixinConfig(AppConfig, DelayMixin):
    pass


class CamelCaseConfig(AppConfig):
    model_config = SettingsConfigDict(alias_generator=to_camel)

    off_delay: int = 30


class AliasChoicesConfig(AppConfig):
    off_delay: int = Field(default=30, validation_alias=AliasChoices("delay", AliasPath("timing", 0)))


@pytest.mark.parametrize(
    ("config_cls", "expected", "absent"),
    [
        (MotionLightConfig, {"off_delay"}, set()),
        (AliasedDelayConfig, {"delay"}, {"off_delay"}),
        (ByNameDelayConfig, {"delay", "off_delay"}, set()),
        (ExplicitNoNameConfig, {"delay"}, {"off_delay"}),
        (AliasChoicesConfig, {"delay", "timing"}, {"off_delay"}),
    ],
)
def test_accepted_config_keys_follow_pydantic_lookup(
    config_cls: type[AppConfig], expected: set[str], absent: set[str]
) -> None:
    """Suggestion candidates are the keys pydantic actually reads, not always the attribute names."""
    keys = set(accepted_config_keys(config_cls))

    assert expected <= keys
    assert not (absent & keys)


class TestAppFactoryUnrecognizedConfigKeyWarning:
    def test_bare_app_config_does_not_warn_on_extras(self, factory: AppFactory, mock_registry: Mock, mock_manifest):
        """A bare AppConfig takes arbitrary keys as intended extras, so none of them warn."""
        config = {"instance_name": "test_instance", "anything": 1, "off_dealy": 5}

        factory.create_single_instance(
            "test_app", mock_manifest, 0, config, as_app_class(make_app_class()), outcomes=AnyIndexOutcomes()
        )

        mock_registry.register_app.assert_called_once()
        mock_registry.record_failure.assert_not_called()

    def test_typed_config_typo_warns_with_suggestion(self, factory: AppFactory, mock_registry: Mock, mock_manifest):
        """A typo'd key on a typed subclass warns once, names the key, and suggests the field."""
        mock_app_class = make_app_class(MotionLightConfig)
        config = {"instance_name": "test_instance", "off_dealy": 5}

        with pytest.warns(UserWarning, match="Unrecognized configuration key") as record:
            factory.create_single_instance(
                "test_app", mock_manifest, 0, config, as_app_class(mock_app_class), outcomes=AnyIndexOutcomes()
            )

        assert len(record) == 1
        msg = str(record[0].message)
        assert "'off_dealy' (did you mean 'off_delay'?)" in msg
        assert "test_app" in msg
        assert "test_instance" in msg
        mock_registry.register_app.assert_called_once()
        validated = mock_app_class.call_args.kwargs["app_config"]
        assert validated.off_delay == 30

    def test_config_overriding_only_inherited_fields_warns_on_typo(
        self, factory: AppFactory, mock_registry: Mock, mock_manifest
    ):
        """Redeclaring an inherited field is still a typed schema, so a typo against it warns."""
        config = {"instance_name": "test_instance", "log_lebel": "INFO"}

        with pytest.warns(UserWarning, match="'log_lebel' \\(did you mean 'log_level'\\?\\)"):
            factory.create_single_instance(
                "test_app",
                mock_manifest,
                0,
                config,
                as_app_class(make_app_class(OverrideOnlyConfig)),
                outcomes=AnyIndexOutcomes(),
            )

        mock_registry.register_app.assert_called_once()

    @pytest.mark.parametrize("config_cls", [MixinOnlyConfig, TrailingMixinConfig], ids=["leading", "trailing"])
    def test_config_with_mixin_fields_warns_on_typo(
        self, factory: AppFactory, mock_registry: Mock, mock_manifest, config_cls: type[AppConfig]
    ):
        """Fields contributed by a plain mixin make the config typed, on either side of ``AppConfig`` in the bases."""
        config = {"instance_name": "test_instance", "off_dealy": 5}

        with pytest.warns(UserWarning, match="'off_dealy' \\(did you mean 'off_delay'\\?\\)"):
            factory.create_single_instance(
                "test_app",
                mock_manifest,
                0,
                config,
                as_app_class(make_app_class(config_cls)),
                outcomes=AnyIndexOutcomes(),
            )

        mock_registry.register_app.assert_called_once()

    def test_typed_config_unrelated_key_warns_without_suggestion(
        self, factory: AppFactory, mock_registry: Mock, mock_manifest
    ):
        """An unrecognized key with no close field match warns without a suggestion."""
        config = {"instance_name": "test_instance", "zzz": 5}

        with pytest.warns(UserWarning, match="'zzz'") as record:
            factory.create_single_instance(
                "test_app",
                mock_manifest,
                0,
                config,
                as_app_class(make_app_class(MotionLightConfig)),
                outcomes=AnyIndexOutcomes(),
            )

        assert "did you mean" not in str(record[0].message)
        mock_registry.register_app.assert_called_once()

    def test_typed_config_suggests_alias_not_field_name(self, factory: AppFactory, mock_registry: Mock, mock_manifest):
        """An aliased field is populated by its alias, so the suggestion names the alias, not the attribute."""
        config = {"instance_name": "test_instance", "off_delay": 5}

        with pytest.warns(UserWarning, match="Unrecognized configuration key") as record:
            factory.create_single_instance(
                "test_app",
                mock_manifest,
                0,
                config,
                as_app_class(make_app_class(AliasedDelayConfig)),
                outcomes=AnyIndexOutcomes(),
            )

        assert "'off_delay' (did you mean 'delay'?)" in str(record[0].message)

    def test_typed_config_incomplete_alias_path_does_not_suggest_itself(
        self, factory: AppFactory, mock_registry: Mock, mock_manifest
    ):
        """A correctly spelled alias-path head whose nested value is missing warns without suggesting itself."""
        config = {"instance_name": "test_instance", "timing": []}

        with pytest.warns(UserWarning, match="'timing'") as record:
            factory.create_single_instance(
                "test_app",
                mock_manifest,
                0,
                config,
                as_app_class(make_app_class(AliasChoicesConfig)),
                outcomes=AnyIndexOutcomes(),
            )

        msg = str(record[0].message)
        assert "did you mean" not in msg
        assert "value went unused" in msg
        mock_registry.register_app.assert_called_once()

    def test_typed_config_aliased_instance_name_does_not_warn(
        self, factory: AppFactory, mock_registry: Mock, mock_manifest
    ):
        """The framework requires the literal instance_name key, so it never warns, even under an alias generator."""
        config = {"instance_name": "test_instance", "offDelay": 5}

        factory.create_single_instance(
            "test_app",
            mock_manifest,
            0,
            config,
            as_app_class(make_app_class(CamelCaseConfig)),
            outcomes=AnyIndexOutcomes(),
        )

        mock_registry.register_app.assert_called_once()
        mock_registry.record_failure.assert_not_called()

    def test_typed_config_all_keys_recognized_does_not_warn(
        self, factory: AppFactory, mock_registry: Mock, mock_manifest
    ):
        """No warning when every key maps to a declared field (pytest escalates warnings to errors)."""
        config = {"instance_name": "test_instance", "off_delay": 5}

        factory.create_single_instance(
            "test_app",
            mock_manifest,
            0,
            config,
            as_app_class(make_app_class(MotionLightConfig)),
            outcomes=AnyIndexOutcomes(),
        )

        mock_registry.register_app.assert_called_once()
        mock_registry.record_failure.assert_not_called()

    def test_typed_config_ignores_dotenv_extras(
        self, factory: AppFactory, mock_registry: Mock, mock_manifest, tmp_path, monkeypatch
    ):
        """Unrelated .env entries folded into model_extra by pydantic-settings never warn."""
        (tmp_path / ".env").write_text("SOME_OTHER_SECRET=1\n")
        monkeypatch.chdir(tmp_path)
        config = {"instance_name": "test_instance", "off_delay": 5}

        mock_app_class = make_app_class(MotionLightConfig)

        factory.create_single_instance(
            "test_app", mock_manifest, 0, config, as_app_class(mock_app_class), outcomes=AnyIndexOutcomes()
        )

        assert "some_other_secret" in mock_app_class.call_args.kwargs["app_config"].model_extra
        mock_registry.register_app.assert_called_once()
        mock_registry.record_failure.assert_not_called()

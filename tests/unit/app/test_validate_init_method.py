"""`validate_init_method` rejects only a base listed before App that would shadow `App.__init__`."""

import pytest

from hassette.app import App, AppConfig
from hassette.app.utils import validate_init_method
from hassette.exceptions import InvalidInheritanceError


class _PlainMixin:
    def helper(self) -> str:
        return "ok"


class _InitMixin:
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)


class _PlainMixinApp(_PlainMixin, App[AppConfig]):
    pass


class _ShadowingApp(_InitMixin, App[AppConfig]):
    pass


class _OwnInitApp(_InitMixin, App[AppConfig]):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)


def test_mixin_without_init_before_app_is_accepted() -> None:
    validate_init_method(_PlainMixinApp)


def test_mixin_with_init_before_app_is_rejected() -> None:
    with pytest.raises(InvalidInheritanceError, match="_InitMixin"):
        validate_init_method(_ShadowingApp)


def test_subclass_defining_own_init_is_accepted() -> None:
    validate_init_method(_OwnInitApp)

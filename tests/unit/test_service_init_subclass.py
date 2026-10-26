"""Unit tests for Service.__init_subclass__'s `required` declaration rule (spec 134 D17)."""

from abc import abstractmethod

import pytest

from hassette.resources.service import Service


def test_concrete_service_without_declaration_fails_at_class_definition() -> None:
    with pytest.raises(TypeError, match="must declare whether it is required"):

        class _Undeclared(Service):  # pyright: ignore[reportUnusedClass]
            async def serve(self) -> None:
                pass


def test_declaration_in_class_body_is_kept() -> None:
    class _Required(Service):
        required = True

        async def serve(self) -> None:
            pass

    class _Optional(Service):
        required = False

        async def serve(self) -> None:
            pass

    assert _Required.required is True
    assert _Optional.required is False


def test_abstract_intermediate_is_skipped_but_its_concrete_subclass_must_declare() -> None:
    class _AbstractService(Service):
        @abstractmethod
        async def serve(self) -> None:
            raise NotImplementedError

    with pytest.raises(TypeError, match="must declare whether it is required"):

        class _Concrete(_AbstractService):  # pyright: ignore[reportUnusedClass]
            async def serve(self) -> None:
                pass


def test_subclass_of_concrete_service_must_redeclare() -> None:
    class _Base(Service):
        required = False

        async def serve(self) -> None:
            pass

    with pytest.raises(TypeError, match="must declare whether it is required"):

        class _Child(_Base):  # pyright: ignore[reportUnusedClass]
            pass


def test_service_base_defaults_to_required() -> None:
    """An abstract-skipped intermediate that is instantiated anyway routes as required, the loud side."""
    assert Service.required is True

"""Unit tests for Service.__init_subclass__ restart_spec warning behavior."""

import warnings
from abc import abstractmethod

import pytest

from hassette.resources.restart import RestartSpec
from hassette.resources.service import Service


class TestServiceSubclassWarning:
    def test_service_subclass_without_restart_spec_warns(self) -> None:
        """Subclass Service without declaring restart_spec triggers UserWarning."""
        with pytest.warns(UserWarning, match="restart_spec"):

            class _NoSpec(Service):
                async def serve(self) -> None:
                    pass

        assert _NoSpec.__name__ == "_NoSpec"

    def test_service_subclass_with_restart_spec_no_warning(self) -> None:
        """Subclass Service with restart_spec declared produces no warning."""
        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)

            class _WithSpec(Service):
                restart_spec = RestartSpec()

                async def serve(self) -> None:
                    pass

        assert _WithSpec.restart_spec == RestartSpec()


class TestAbstractServiceNoWarning:
    def test_abstract_service_subclass_no_warning(self) -> None:
        """Abstract Service subclasses (with abstract methods) do not trigger the warning."""
        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)

            class _AbstractService(Service):
                @abstractmethod
                async def serve(self) -> None:
                    raise NotImplementedError

                @abstractmethod
                async def abstract_method(self) -> None:
                    raise NotImplementedError

        # Concrete subclass of the abstract class DOES warn (no restart_spec)
        with pytest.warns(UserWarning, match="restart_spec"):

            class _ConcreteSubclass(_AbstractService):
                async def serve(self) -> None:
                    pass

                async def abstract_method(self) -> None:
                    pass

        assert _ConcreteSubclass.__name__ == "_ConcreteSubclass"

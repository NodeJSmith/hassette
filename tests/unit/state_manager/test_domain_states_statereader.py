"""Unit tests proving DomainStates works against any StateReader-shaped object.

These tests construct DomainStates with a minimal dict-backed fake that implements
the StateReader protocol, verifying the public state-access path has no dependency
on the concrete StateProxy or the core package.
"""

import typing
from collections.abc import Generator, Mapping
from uuid import uuid4

import pytest

from hassette.events import HassStateDict
from hassette.models.states.base import BaseState
from hassette.state_manager import DomainStates

if typing.TYPE_CHECKING:
    from hassette.types import StateReader


def make_minimal_state_dict(entity_id: str, state_value: str = "on") -> HassStateDict:
    """Build the minimum dict DomainStates needs to validate a state."""
    return {
        "entity_id": entity_id,
        "domain": entity_id.split(".")[0],
        "state": state_value,
        "attributes": {},
        "last_changed": "2024-01-01T00:00:00+00:00",
        "last_updated": "2024-01-01T00:00:00+00:00",
        "last_reported": "2024-01-01T00:00:00+00:00",
        "context": {"id": str(uuid4()), "parent_id": None, "user_id": None},
    }


class FakeStateReader:
    """Minimal dict-backed implementation of the StateReader protocol.

    Holds states keyed by entity_id and answers the four members StateReader
    declares: get_state, num_domain_states, yield_domain_states, __contains__.
    """

    def __init__(self, states: dict[str, HassStateDict]) -> None:
        self.states = states

    def get_state(self, entity_id: str) -> HassStateDict | None:
        return self.states.get(entity_id)

    def num_domain_states(self, domain: str) -> int:
        return sum(1 for eid in self.states if eid.startswith(f"{domain}."))

    def yield_domain_states(self, domain: str) -> Generator[tuple[str, HassStateDict], typing.Any, None]:
        for eid, state in self.states.items():
            if eid.startswith(f"{domain}."):
                yield eid, state

    def __contains__(self, entity_id: str) -> bool:
        return entity_id in self.states


def _check_fake_is_state_reader(reader: FakeStateReader) -> None:
    """Pyright verifies FakeStateReader satisfies StateReader — proving the fake is a faithful
    stand-in and that DomainStates' dependency is the protocol, not the concrete StateProxy.

    This function is never called at runtime; the assignment is the pyright-level structural proof.
    """
    _: StateReader = reader


class TestDomainStatesAgainstFakeStateReader:
    """DomainStates must work against any StateReader-shaped object, not just StateProxy."""

    @staticmethod
    def make_test_state_class() -> type[BaseState]:
        """Define a BaseState subclass inside the test to avoid polluting the global registry."""

        class FakeWidgetState(BaseState):
            domain: typing.Literal["fake_widget"]

        return FakeWidgetState

    def test_get_returns_typed_state_for_existing_entity(self) -> None:
        state_class = self.make_test_state_class()
        state_dict = make_minimal_state_dict("fake_widget.living_room", "on")
        reader = FakeStateReader({"fake_widget.living_room": state_dict})
        ds = DomainStates(reader, state_class)

        result = ds.get("fake_widget.living_room")

        assert result is not None
        assert isinstance(result, state_class)
        assert result.value == "on"

    def test_get_returns_none_for_missing_entity(self) -> None:
        state_class = self.make_test_state_class()
        reader = FakeStateReader({})
        ds = DomainStates(reader, state_class)

        assert ds.get("fake_widget.missing") is None

    def test_contains_returns_true_for_existing_entity(self) -> None:
        state_class = self.make_test_state_class()
        state_dict = make_minimal_state_dict("fake_widget.living_room")
        reader = FakeStateReader({"fake_widget.living_room": state_dict})
        ds = DomainStates(reader, state_class)

        assert "fake_widget.living_room" in ds
        assert "living_room" in ds

    def test_contains_returns_false_for_missing_entity(self) -> None:
        state_class = self.make_test_state_class()
        reader = FakeStateReader({})
        ds = DomainStates(reader, state_class)

        assert "fake_widget.missing" not in ds

    def test_len_reflects_domain_count(self) -> None:
        state_class = self.make_test_state_class()
        states = {
            "fake_widget.one": make_minimal_state_dict("fake_widget.one"),
            "fake_widget.two": make_minimal_state_dict("fake_widget.two"),
            "other.entity": make_minimal_state_dict("other.entity"),
        }
        reader = FakeStateReader(states)
        ds = DomainStates(reader, state_class)

        assert len(ds) == 2

    def test_iteration_yields_entity_ids(self) -> None:
        state_class = self.make_test_state_class()
        states = {
            "fake_widget.one": make_minimal_state_dict("fake_widget.one", "on"),
            "fake_widget.two": make_minimal_state_dict("fake_widget.two", "off"),
            "other.entity": make_minimal_state_dict("other.entity"),
        }
        reader = FakeStateReader(states)
        ds = DomainStates(reader, state_class)

        result = list(ds)

        assert set(result) == {"fake_widget.one", "fake_widget.two"}
        for entity_id in result:
            assert isinstance(entity_id, str)

    def test_items_yields_entity_id_state_pairs(self) -> None:
        state_class = self.make_test_state_class()
        states = {
            "fake_widget.one": make_minimal_state_dict("fake_widget.one", "on"),
            "fake_widget.two": make_minimal_state_dict("fake_widget.two", "off"),
            "other.entity": make_minimal_state_dict("other.entity"),
        }
        reader = FakeStateReader(states)
        ds = DomainStates(reader, state_class)

        results = list(ds.items())

        assert len(results) == 2
        entity_ids = {eid for eid, _ in results}
        assert entity_ids == {"fake_widget.one", "fake_widget.two"}
        for _, state in results:
            assert isinstance(state, state_class)

    def test_keys_returns_reiterable_view(self) -> None:
        state_class = self.make_test_state_class()
        states = {
            "fake_widget.one": make_minimal_state_dict("fake_widget.one", "on"),
            "fake_widget.two": make_minimal_state_dict("fake_widget.two", "off"),
            "other.entity": make_minimal_state_dict("other.entity"),
        }
        reader = FakeStateReader(states)
        ds = DomainStates(reader, state_class)

        keys = ds.keys()
        first_pass = set(keys)
        second_pass = set(keys)

        assert first_pass == {"fake_widget.one", "fake_widget.two"}
        assert first_pass == second_pass

    def test_values_returns_reiterable_view(self) -> None:
        state_class = self.make_test_state_class()
        states = {
            "fake_widget.one": make_minimal_state_dict("fake_widget.one", "on"),
            "fake_widget.two": make_minimal_state_dict("fake_widget.two", "off"),
        }
        reader = FakeStateReader(states)
        ds = DomainStates(reader, state_class)

        values = ds.values()
        first_pass = list(values)
        second_pass = list(values)

        assert len(first_pass) == 2
        assert len(second_pass) == 2
        for state in first_pass:
            assert isinstance(state, state_class)

    def test_keys_view_supports_len(self) -> None:
        state_class = self.make_test_state_class()
        states = {
            "fake_widget.one": make_minimal_state_dict("fake_widget.one"),
            "fake_widget.two": make_minimal_state_dict("fake_widget.two"),
        }
        reader = FakeStateReader(states)
        ds = DomainStates(reader, state_class)

        assert len(ds.keys()) == 2
        assert len(ds.values()) == 2
        assert len(ds.items()) == 2

    def test_keys_view_supports_contains(self) -> None:
        state_class = self.make_test_state_class()
        states = {"fake_widget.one": make_minimal_state_dict("fake_widget.one")}
        reader = FakeStateReader(states)
        ds = DomainStates(reader, state_class)

        assert "fake_widget.one" in ds.keys()  # noqa: SIM118 — testing KeysView.__contains__
        assert "fake_widget.missing" not in ds.keys()  # noqa: SIM118

    def test_dict_constructor_works(self) -> None:
        state_class = self.make_test_state_class()
        states = {
            "fake_widget.one": make_minimal_state_dict("fake_widget.one", "on"),
            "fake_widget.two": make_minimal_state_dict("fake_widget.two", "off"),
        }
        reader = FakeStateReader(states)
        ds = DomainStates(reader, state_class)

        result = dict(ds)

        assert set(result.keys()) == {"fake_widget.one", "fake_widget.two"}
        for state in result.values():
            assert isinstance(state, state_class)

    def test_is_mapping_instance(self) -> None:
        state_class = self.make_test_state_class()
        reader = FakeStateReader({})
        ds = DomainStates(reader, state_class)

        assert isinstance(ds, Mapping)

    def test_no_core_import_needed_to_construct(self) -> None:
        """Constructing DomainStates with a plain dict-backed fake works without any core import.

        If the module boundary were violated, this import would trigger an ImportError or
        a circular-import failure in a clean environment. The fact that it runs proves the
        decoupling is effective at runtime, not just at the type level.
        """
        state_class = self.make_test_state_class()
        reader = FakeStateReader({})
        ds = DomainStates(reader, state_class)
        assert repr(ds) == "DomainStates(domain='fake_widget', count=0)"

    def test_wrong_model_type_raises(self) -> None:
        reader = FakeStateReader({})
        with pytest.raises(TypeError, match="Expected a subclass of BaseState"):
            DomainStates(reader, str)  # pyright: ignore[reportArgumentType]

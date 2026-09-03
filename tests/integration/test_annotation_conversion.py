# pyright: reportInvalidTypeForm=none
"""Tests for dependency injection type conversion, unions, and complex types."""

from collections.abc import Callable
from typing import Annotated, Any

import pytest

from hassette import STATE_REGISTRY, A, D
from hassette.bus.injection import ParameterInjector
from hassette.conversion import ANNOTATION_CONVERTER
from hassette.events import Event, RawStateChangeEvent
from hassette.exceptions import DependencyResolutionError
from hassette.models import states
from hassette.testing import make_full_state_change_event, make_light_state_dict
from hassette.utils.type_utils import get_type_and_details, get_typed_signature


def get_random_model(exclude_models: list[type[states.BaseState]]) -> type[states.BaseState]:
    all_models = [states.LightState, states.SwitchState, states.SensorState]
    for model in all_models:
        if model not in exclude_models:
            return model
    return states.BaseState  # Fallback, should not happen in this test


def inject(handler: Callable[..., Any], event: Event) -> dict[str, Any]:
    """Resolve `handler`'s parameters against `event` the way the bus does at dispatch time."""
    signature = get_typed_signature(handler)
    injector = ParameterInjector(handler.__name__, signature)
    return injector.inject_parameters(event)


def value_handler(annotation: Any) -> Callable[..., None]:
    """Build a handler with a single `value` parameter carrying `annotation`.

    The complex-type conversion cases differ only in that annotation, so synthesizing it lets them
    share one parametrized body instead of one near-identical handler definition each.
    """

    def handler(value):
        pass

    handler.__annotations__ = {"value": annotation}
    return handler


class TestDependencyInjectionHandlesTypeConversion:
    """Test that dependency injection handles type conversion correctly."""

    async def test_raw_state_change_event_extractor_returns_event(self, state_change_events: list[RawStateChangeEvent]):
        """Test that RawStateChangeEvent extractor returns the event as-is."""
        for state_change_event in state_change_events:

            def handler(event: RawStateChangeEvent):
                pass

            result = inject(handler, state_change_event)["event"]

            assert result is state_change_event, "Extractor should return the event as-is"

    async def test_state_conversion(self, state_change_events_with_new_state: list[RawStateChangeEvent]):
        """Test that StateNew converts BaseState to domain-specific state type."""
        for state_change_event in state_change_events_with_new_state:
            model = STATE_REGISTRY.resolve(domain=state_change_event.payload.data.domain)
            domain = state_change_event.payload.data.domain

            _, annotation_details = get_type_and_details(D.StateNew[model])
            result = annotation_details.extractor(state_change_event)
            state = ANNOTATION_CONVERTER.convert(result, model)

            assert isinstance(state, model), f"State should be converted to {model.__name__}"
            assert state.entity_id.startswith(f"{domain}."), f"Entity ID should have {domain} domain"

    async def test_annotated_as_base_state_stays_base_state(
        self, state_change_events_with_new_state: list[RawStateChangeEvent]
    ):
        """Test that StateNew[BaseState] returns BaseState without conversion."""
        for state_change_event in state_change_events_with_new_state:
            domain = state_change_event.payload.data.domain

            _, annotation_details = get_type_and_details(D.StateNew[states.BaseState])
            result = annotation_details.extractor(state_change_event)
            state = ANNOTATION_CONVERTER.convert(result, states.BaseState)

            assert isinstance(state, states.BaseState), f"State should be BaseState, got {type(state)}"
            assert state.entity_id.startswith(f"{domain}."), f"Entity ID should have {domain} domain"

    async def test_maybe_state_conversion(self, state_change_events: list[RawStateChangeEvent]):
        """Test that MaybeStateNew converts BaseState to domain-specific state type."""
        for state_change_event in state_change_events:
            model = STATE_REGISTRY.resolve(domain=state_change_event.payload.data.domain)
            domain = state_change_event.payload.data.domain

            def handler(new_state: D.MaybeStateNew[model]):
                pass

            kwargs = inject(handler, state_change_event)

            state = kwargs["new_state"]
            if state_change_event.payload.data.new_state is None:
                assert state is None, "State should be None when not present"
            else:
                assert isinstance(state, model), f"State should be converted to {model.__name__}, got {type(state)}"
                assert state.entity_id.startswith(f"{domain}."), f"Entity ID should have {domain} domain"

    async def test_maybe_state_as_base_state_stays_base_state(self, state_change_events: list[RawStateChangeEvent]):
        """Test that MaybeStateNew[BaseState] returns BaseState without conversion."""
        for state_change_event in state_change_events:
            domain = state_change_event.payload.data.domain

            def handler(new_state: D.MaybeStateNew[states.BaseState]):
                # results.append(new_state)
                pass

            kwargs = inject(handler, state_change_event)

            state = kwargs["new_state"]
            if state_change_event.payload.data.new_state is None:
                assert state is None, "State should be None when not present"
            else:
                assert isinstance(state, states.BaseState), f"State should be BaseState, got {type(state)}"
                assert state.entity_id.startswith(f"{domain}."), f"Entity ID should have {domain} domain"

    async def test_new_state_with_maybe_old_state_converted_correctly(
        self, state_change_events_with_new_state: list[RawStateChangeEvent]
    ):
        """Test StateNew and MaybeStateOld conversion when only new_state is present."""
        for state_change_event in state_change_events_with_new_state:
            model = STATE_REGISTRY.resolve(domain=state_change_event.payload.data.domain)

            def handler(new_state: D.StateNew[model], old_state: D.MaybeStateOld[model]):
                pass

            kwargs = inject(handler, state_change_event)

            old_state = kwargs["old_state"]

            if state_change_event.payload.data.old_state is None:
                assert old_state is None, "Old state should be None when not present"
            else:
                assert isinstance(old_state, model), f"Old state should be {model.__name__}, got {type(old_state)}"

    async def test_maybe_new_state_with_old_state_converted_correctly(
        self, state_change_events_with_old_state: list[RawStateChangeEvent]
    ):
        """Test MaybeStateNew and StateOld conversion when only old_state is present."""
        for state_change_event in state_change_events_with_old_state:
            model = STATE_REGISTRY.resolve(domain=state_change_event.payload.data.domain)

            def handler(new_state: D.MaybeStateNew[model], old_state: D.StateOld[model]):
                pass

            kwargs = inject(handler, state_change_event)

            new_state = kwargs["new_state"]
            old_state = kwargs["old_state"]

            if state_change_event.payload.data.new_state is None:
                assert new_state is None, "New state should be None when not present"
            else:
                assert isinstance(new_state, model), f"New state should be {model.__name__}, got {type(new_state)}"

            assert isinstance(old_state, model), f"Old state should be {model.__name__}, got {type(old_state)}"

    async def test_both_states_converted_correctly(
        self, state_change_events_with_both_states: list[RawStateChangeEvent]
    ):
        """Test StateNew and StateOld conversion when both states are present."""
        for state_change_event in state_change_events_with_both_states:
            model = STATE_REGISTRY.resolve(domain=state_change_event.payload.data.domain)

            def handler(new_state: D.StateNew[model], old_state: D.StateOld[model]):
                pass

            kwargs = inject(handler, state_change_event)

            new_state = kwargs["new_state"]
            old_state = kwargs["old_state"]

            assert isinstance(new_state, model), f"New state should be {model.__name__}, got {type(new_state)}"
            assert isinstance(old_state, model), f"Old state should be {model.__name__}, got {type(old_state)}"

    async def test_typed_state_change_event(self, state_change_events_with_new_state: list[RawStateChangeEvent]):
        """Test TypedStateChangeEvent provides typed states."""
        for state_change_event in state_change_events_with_new_state:
            model = STATE_REGISTRY.resolve(domain=state_change_event.payload.data.domain)

            def handler(event: D.TypedStateChangeEvent[model]):
                pass

            kwargs = inject(handler, state_change_event)

            event = kwargs["event"]
            new_state = event.payload.data.new_state
            old_state = event.payload.data.old_state

            assert isinstance(new_state, model), f"New state should be {model.__name__}, got {type(new_state)}"
            if old_state is not None:
                assert isinstance(old_state, model), f"Old state should be {model.__name__}, got {type(old_state)}"

    async def test_typed_annotation_with_wrong_type_raise_validation_error(
        self, state_change_events_with_new_state: list[RawStateChangeEvent]
    ):
        """Test TypedStateChangeEvent provides typed states."""
        for state_change_event in state_change_events_with_new_state:
            correct_model = STATE_REGISTRY.resolve(domain=state_change_event.payload.data.domain)
            incorrect_model = get_random_model([correct_model])

            def typed_state_change_handler(event: D.TypedStateChangeEvent[incorrect_model]):
                pass

            def new_state_handler(new_state: D.StateNew[incorrect_model]):
                pass

            for handler in (typed_state_change_handler, new_state_handler):
                with pytest.raises(DependencyResolutionError, match=r".*failed to convert parameter.*"):
                    inject(handler, state_change_event)


class TestDependencyInjectionTypeConversionHandlesUnions:
    """Test that dependency injection handles Union type annotations correctly."""

    async def test_typed_annotation_union_finds_correct_type(
        self, state_change_events_with_new_state: list[RawStateChangeEvent]
    ):
        """Test TypedStateChangeEvent provides typed states."""
        for state_change_event in state_change_events_with_new_state:
            correct_model = STATE_REGISTRY.resolve(domain=state_change_event.payload.data.domain)
            incorrect_model = get_random_model([correct_model])

            def typed_state_change_handler(event: D.TypedStateChangeEvent[incorrect_model | correct_model]):
                pass

            def new_state_handler(new_state: D.StateNew[incorrect_model | correct_model]):
                pass

            for handler in (typed_state_change_handler, new_state_handler):
                # consider not raising as success
                inject(handler, state_change_event)

    async def test_typed_annotation_union_with_all_wrong_types_raises(
        self, state_change_events_with_new_state: list[RawStateChangeEvent]
    ):
        """Test TypedStateChangeEvent provides typed states."""
        for state_change_event in state_change_events_with_new_state:
            correct_model = STATE_REGISTRY.resolve(domain=state_change_event.payload.data.domain)
            incorrect_model = get_random_model([correct_model])
            another_incorrect_model = get_random_model([correct_model, incorrect_model])

            def typed_state_change_handler(event: D.TypedStateChangeEvent[incorrect_model | another_incorrect_model]):
                pass

            def new_state_handler(new_state: D.StateNew[incorrect_model | another_incorrect_model]):
                pass

            for handler in (typed_state_change_handler, new_state_handler):
                with pytest.raises(DependencyResolutionError, match=r".* to hassette.models.states.*"):
                    inject(handler, state_change_event)


class TestDependencyInjectionTypeConversionHandlesComplexTypes:
    """Test that nested container annotations convert their elements to the annotated types."""

    @pytest.mark.parametrize(
        ("old_attrs", "new_attrs", "annotation", "expected"),
        # dup-ignore-start: rows of one pytest.param table — the repeated shape *is* the table,
        # and each row is a distinct conversion case. Collapsing rows would delete test cases,
        # not duplication.
        [
            pytest.param(
                {"rgb_color": [255, 0, 0]},
                {"rgb_color": ["0", "255", "0"]},
                Annotated[list[int], A.get_attr_new("rgb_color")],
                [0, 255, 0],
                id="list_int_converts_str_elements",
            ),
            pytest.param(
                {"rgb_color": [255, 0, 0]},
                {"rgb_color": [12345, "67890", "13579"]},
                Annotated[list[int], A.get_attr_new("rgb_color")],
                [12345, 67890, 13579],
                id="list_int_converts_mixed_elements",
            ),
            pytest.param(
                {"rgb_color": [255, 0, 0]},
                {"rgb_color": [12345, "test", "13579"]},
                Annotated[list[int | str], A.get_attr_new("rgb_color")],
                [12345, "test", 13579],
                id="list_int_or_str_converts_what_it_can",
            ),
            pytest.param(
                {"rgb_color": [255, 0, 0]},
                {"rgb_color": [12345, "test", "13579"]},
                Annotated[list[str | int], A.get_attr_new("rgb_color")],
                ["12345", "test", "13579"],
                id="list_str_or_int_converts_all_to_str",
            ),
            pytest.param(
                {"rgb_color": None},
                {"rgb_color": [0, 255, 0]},
                Annotated[tuple[int], A.get_attr_new("rgb_color")],
                (0, 255, 0),
                id="tuple_single_arg_from_list",
            ),
            pytest.param(
                {"rgb_color": None},
                {"rgb_color": [0, 255, 0]},
                Annotated[tuple[int, ...], A.get_attr_new("rgb_color")],
                (0, 255, 0),
                id="tuple_ellipsis_from_list",
            ),
            pytest.param(
                {"rgb_color": None},
                {"rgb_color": [0, 255, 0]},
                Annotated[tuple[int, int, int], A.get_attr_new("rgb_color")],
                (0, 255, 0),
                id="tuple_repeated_args_from_list",
            ),
            pytest.param(
                {"rgb_color": None},
                {"rgb_color": (0, 255, 0)},
                Annotated[list[int], A.get_attr_new("rgb_color")],
                [0, 255, 0],
                id="list_int_from_tuple",
            ),
            pytest.param(
                {"color_temp": 250},
                {"color_temp": "400"},
                Annotated[dict[str, int], A.get_attrs_new(["color_temp"])],
                {"color_temp": 400},
                id="dict_str_int_converts_values",
            ),
            pytest.param(
                {"color_temp": 250, "effect": None},
                {"color_temp": "400", "effect": "blink"},
                Annotated[dict[str, int | str], A.get_attrs_new(["color_temp", "effect"])],
                {"color_temp": 400, "effect": "blink"},
                id="dict_str_int_or_str_converts_each_value",
            ),
        ],
        # dup-ignore-end
    )
    async def test_nested_annotation_converts_elements(
        self,
        old_attrs: dict[str, Any],
        new_attrs: dict[str, Any],
        annotation: Any,
        expected: Any,
    ):
        """Elements of a nested container annotation are converted to the annotated element type."""
        light_event = make_full_state_change_event(
            entity_id="light.kitchen",
            old_state=make_light_state_dict(**old_attrs),
            new_state=make_light_state_dict(**new_attrs),
        )

        assert inject(value_handler(annotation), light_event) == {"value": expected}

    async def test_nested_annotation_raises_when_an_element_cannot_convert(self):
        """A list[int] annotation raises when any element is not convertible to int."""
        light_event = make_full_state_change_event(
            entity_id="light.kitchen",
            old_state=make_light_state_dict(rgb_color=[255, 0, 0]),
            new_state=make_light_state_dict(rgb_color=[12345, "test", "13579"]),
        )
        handler = value_handler(Annotated[list[int], A.get_attr_new("rgb_color")])

        with pytest.raises(DependencyResolutionError, match=r".*failed to convert parameter 'value'.*"):
            inject(handler, light_event)

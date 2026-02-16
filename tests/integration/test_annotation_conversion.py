# pyright: reportInvalidTypeForm=none

# disabling reportInvalidTypeForm - i know this is invalid, but it works best for the dynamic
# nature of the tests

"""Tests for dependency injection type conversion, unions, and complex types."""

from typing import Annotated

import pytest

from hassette import STATE_REGISTRY, A, D
from hassette.bus.extraction import extract_from_annotated
from hassette.bus.injection import ParameterInjector
from hassette.conversion import ANNOTATION_CONVERTER
from hassette.events import RawStateChangeEvent
from hassette.exceptions import DependencyResolutionError
from hassette.models import states
from hassette.test_utils import make_full_state_change_event, make_light_state_dict
from hassette.utils.type_utils import get_typed_signature


def get_random_model(exclude_models: list[type[states.BaseState]]) -> type[states.BaseState]:
    all_models = [states.LightState, states.SwitchState, states.SensorState]
    for model in all_models:
        if model not in exclude_models:
            return model
    return states.BaseState  # Fallback, should not happen in this test


class TestDependencyInjectionHandlesTypeConversion:
    """Test that dependency injection handles type conversion correctly."""

    async def test_raw_state_change_event_extractor_returns_event(self, state_change_events: list[RawStateChangeEvent]):
        """Test that RawStateChangeEvent extractor returns the event as-is."""
        for state_change_event in state_change_events:

            def handler(event: RawStateChangeEvent):
                pass

            signature = get_typed_signature(handler)
            injector = ParameterInjector(handler.__name__, signature)
            kwargs = injector.inject_parameters(state_change_event)
            result = kwargs["event"]

            assert result is state_change_event, "Extractor should return the event as-is"

    async def test_state_conversion(self, state_change_events_with_new_state: list[RawStateChangeEvent]):
        """Test that StateNew converts BaseState to domain-specific state type."""

        for state_change_event in state_change_events_with_new_state:
            model = STATE_REGISTRY.resolve(domain=state_change_event.payload.data.domain)
            domain = state_change_event.payload.data.domain

            _, annotation_details = extract_from_annotated(D.StateNew[model])
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

            _, annotation_details = extract_from_annotated(D.StateNew[states.BaseState])
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

            signature = get_typed_signature(handler)
            injector = ParameterInjector(handler.__name__, signature)
            kwargs = injector.inject_parameters(state_change_event)

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

            signature = get_typed_signature(handler)
            injector = ParameterInjector(handler.__name__, signature)
            kwargs = injector.inject_parameters(state_change_event)

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

            signature = get_typed_signature(handler)
            injector = ParameterInjector(handler.__name__, signature)
            kwargs = injector.inject_parameters(state_change_event)

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

            signature = get_typed_signature(handler)
            injector = ParameterInjector(handler.__name__, signature)
            kwargs = injector.inject_parameters(state_change_event)

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

            signature = get_typed_signature(handler)
            injector = ParameterInjector(handler.__name__, signature)
            kwargs = injector.inject_parameters(state_change_event)

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

            signature = get_typed_signature(handler)
            injector = ParameterInjector(handler.__name__, signature)
            kwargs = injector.inject_parameters(state_change_event)

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
                signature = get_typed_signature(handler)
                injector = ParameterInjector(handler.__name__, signature)

                with pytest.raises(DependencyResolutionError, match=r".*failed to convert parameter.*"):
                    injector.inject_parameters(state_change_event)


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
                signature = get_typed_signature(handler)
                injector = ParameterInjector(handler.__name__, signature)

                # consider not raising as successs
                injector.inject_parameters(state_change_event)

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
                signature = get_typed_signature(handler)
                injector = ParameterInjector(handler.__name__, signature)

                with pytest.raises(DependencyResolutionError, match=r".* to hassette.models.states.*"):
                    injector.inject_parameters(state_change_event)


class TestDependencyInjectionTypeConversionHandlesComplexTypes:
    async def test_typed_annotation_handles_list_of_int(self):
        """Asserts that when we have a nested type of list[int], the elements are converted to int."""
        light_state_old = make_light_state_dict(rgb_color=[255, 0, 0])
        light_state_new = make_light_state_dict(rgb_color=["0", "255", "0"])
        light_event = make_full_state_change_event(
            entity_id="light.kitchen", old_state=light_state_old, new_state=light_state_new
        )

        def new_state_handler(rgb_color: Annotated[list[int], A.get_attr_new("rgb_color")]):
            pass

        signature = get_typed_signature(new_state_handler)
        injector = ParameterInjector(new_state_handler.__name__, signature)

        # succeeds if there is no exception
        kwargs = injector.inject_parameters(light_event)
        assert kwargs == {"rgb_color": [0, 255, 0]}

    async def test_typed_annotation_handles_dict_str_int(self):
        """Asserts that when the dict has str keys and int values, the values are converted to int."""
        light_state_old = make_light_state_dict(color_temp=250)
        light_state_new = make_light_state_dict(color_temp="400")
        light_event = make_full_state_change_event(
            entity_id="light.kitchen", old_state=light_state_old, new_state=light_state_new
        )

        def new_state_handler(attrs: Annotated[dict[str, int], A.get_attrs_new(["color_temp"])]):
            pass

        signature = get_typed_signature(new_state_handler)
        injector = ParameterInjector(new_state_handler.__name__, signature)

        # succeeds if there is no exception
        kwargs = injector.inject_parameters(light_event)
        assert kwargs == {"attrs": {"color_temp": 400}}

    async def test_typed_annotation_handles_dict_mixed_type(self):
        """Asserts that when the dict has mixed types, each value is converted to the correct type."""
        light_state_old = make_light_state_dict(color_temp=250, effect=None)
        light_state_new = make_light_state_dict(color_temp="400", effect="blink")
        light_event = make_full_state_change_event(
            entity_id="light.kitchen", old_state=light_state_old, new_state=light_state_new
        )

        def new_state_handler(attrs: Annotated[dict[str, int | str], A.get_attrs_new(["color_temp", "effect"])]):
            pass

        signature = get_typed_signature(new_state_handler)
        injector = ParameterInjector(new_state_handler.__name__, signature)

        # succeeds if there is no exception
        kwargs = injector.inject_parameters(light_event)
        assert kwargs == {"attrs": {"color_temp": 400, "effect": "blink"}}

    async def test_typed_annotation_handles_incoming_elements_mixed_types(self):
        """Asserts that when the element type is int and all elements can be converted to int, they are converted."""
        light_state_old = make_light_state_dict(rgb_color=[255, 0, 0])
        light_state_new = make_light_state_dict(rgb_color=[12345, "67890", "13579"])
        light_event = make_full_state_change_event(
            entity_id="light.kitchen", old_state=light_state_old, new_state=light_state_new
        )

        def new_state_handler(rgb_color: Annotated[list[int], A.get_attr_new("rgb_color")]):
            pass

        signature = get_typed_signature(new_state_handler)
        injector = ParameterInjector(new_state_handler.__name__, signature)

        # succeeds if there is no exception
        kwargs = injector.inject_parameters(light_event)
        assert kwargs == {"rgb_color": [12345, 67890, 13579]}

    async def test_typed_annotation_handles_incoming_elements_mixed_types_cannot_convert_raises(self):
        """Asserts that when the element type is int and not all elements can be converted, raises."""
        light_state_old = make_light_state_dict(rgb_color=[255, 0, 0])
        light_state_new = make_light_state_dict(rgb_color=[12345, "test", "13579"])
        light_event = make_full_state_change_event(
            entity_id="light.kitchen", old_state=light_state_old, new_state=light_state_new
        )

        def new_state_handler(rgb_color: Annotated[list[int], A.get_attr_new("rgb_color")]):
            pass

        signature = get_typed_signature(new_state_handler)
        injector = ParameterInjector(new_state_handler.__name__, signature)

        # succeeds if there is no exception
        with pytest.raises(DependencyResolutionError, match=r".*failed to convert parameter 'rgb_color'.*"):
            injector.inject_parameters(light_event)

    async def test_typed_annotation_handles_incoming_elements_mixed_types_can_convert_converts_successfully(self):
        """Asserts that when the union starts with int, all elements that can be converted to int are converted."""
        light_state_old = make_light_state_dict(rgb_color=[255, 0, 0])
        light_state_new = make_light_state_dict(rgb_color=[12345, "test", "13579"])
        light_event = make_full_state_change_event(
            entity_id="light.kitchen", old_state=light_state_old, new_state=light_state_new
        )

        def new_state_handler(rgb_color: Annotated[list[int | str], A.get_attr_new("rgb_color")]):
            pass

        signature = get_typed_signature(new_state_handler)
        injector = ParameterInjector(new_state_handler.__name__, signature)

        # succeeds if there is no exception
        kwargs = injector.inject_parameters(light_event)
        assert kwargs == {"rgb_color": [12345, "test", 13579]}

    async def test_typed_annotation_handles_incoming_elements_with_str_annotation_converts_all_to_str(self):
        """
        Asserts that when the union starts with str, all elements are converted to str, regardless of other
        types in the Union
        """

        light_state_old = make_light_state_dict(rgb_color=[255, 0, 0])
        light_state_new = make_light_state_dict(rgb_color=[12345, "test", "13579"])
        light_event = make_full_state_change_event(
            entity_id="light.kitchen", old_state=light_state_old, new_state=light_state_new
        )

        def new_state_handler(rgb_color: Annotated[list[str | int], A.get_attr_new("rgb_color")]):
            pass

        signature = get_typed_signature(new_state_handler)
        injector = ParameterInjector(new_state_handler.__name__, signature)

        # succeeds if there is no exception
        kwargs = injector.inject_parameters(light_event)
        assert kwargs == {"rgb_color": ["12345", "test", "13579"]}

    async def test_rgb_color_from_list_int_to_tuple_int_single_t_conversion(self):
        """Asserts that when we annotated with tuple[int] and receive multiple int elements,
        we still handle it correctly by converting to a tuple.
        """
        light_state_old = make_light_state_dict(rgb_color=None)
        light_state_new = make_light_state_dict(rgb_color=[0, 255, 0])
        light_event = make_full_state_change_event(
            entity_id="light.kitchen", old_state=light_state_old, new_state=light_state_new
        )

        def new_state_handler(rgb_color: Annotated[tuple[int], A.get_attr_new("rgb_color")]):
            pass

        signature = get_typed_signature(new_state_handler)
        injector = ParameterInjector(new_state_handler.__name__, signature)

        # succeeds if there is no exception
        kwargs = injector.inject_parameters(light_event)
        assert kwargs == {"rgb_color": (0, 255, 0)}

    async def test_rgb_color_from_list_int_to_tuple_int_ellipses_conversion(self):
        """Asserts that when we have a nested type of tuple[int, ...], the elements are converted to int."""
        light_state_old = make_light_state_dict(rgb_color=None)
        light_state_new = make_light_state_dict(rgb_color=[0, 255, 0])
        light_event = make_full_state_change_event(
            entity_id="light.kitchen", old_state=light_state_old, new_state=light_state_new
        )

        def new_state_handler(rgb_color: Annotated[tuple[int, ...], A.get_attr_new("rgb_color")]):
            pass

        signature = get_typed_signature(new_state_handler)
        injector = ParameterInjector(new_state_handler.__name__, signature)

        # succeeds if there is no exception
        kwargs = injector.inject_parameters(light_event)
        assert kwargs == {"rgb_color": (0, 255, 0)}

    async def test_rgb_color_from_list_int_to_tuple_int_repeated_conversion(self):
        """Asserts that when we have a nested type of tuple[int, int, int], the elements are converted to int."""
        light_state_old = make_light_state_dict(rgb_color=None)
        light_state_new = make_light_state_dict(rgb_color=[0, 255, 0])
        light_event = make_full_state_change_event(
            entity_id="light.kitchen", old_state=light_state_old, new_state=light_state_new
        )

        def new_state_handler(rgb_color: Annotated[tuple[int, int, int], A.get_attr_new("rgb_color")]):
            pass

        signature = get_typed_signature(new_state_handler)
        injector = ParameterInjector(new_state_handler.__name__, signature)

        # succeeds if there is no exception
        kwargs = injector.inject_parameters(light_event)
        assert kwargs == {"rgb_color": (0, 255, 0)}

    async def test_rgb_color_from_tuple_int_to_list_int_conversion(self):
        """Asserts that when we have a nested type of tuple[int, int, int], the elements are converted to int."""
        light_state_old = make_light_state_dict(rgb_color=None)
        light_state_new = make_light_state_dict(rgb_color=(0, 255, 0))
        light_event = make_full_state_change_event(
            entity_id="light.kitchen", old_state=light_state_old, new_state=light_state_new
        )

        def new_state_handler(rgb_color: Annotated[list[int], A.get_attr_new("rgb_color")]):
            pass

        signature = get_typed_signature(new_state_handler)
        injector = ParameterInjector(new_state_handler.__name__, signature)

        # succeeds if there is no exception
        kwargs = injector.inject_parameters(light_event)
        assert kwargs == {"rgb_color": [0, 255, 0]}

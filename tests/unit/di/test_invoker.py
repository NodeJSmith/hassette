"""Unit tests for CallableInvoker."""

import pytest

from hassette.di import CallableInvoker, InjectionParam, identity


class SourceA:
    pass


class SourceB:
    pass


class TestCallableInvoker:
    def test_empty_plan_returns_empty_dict(self):
        invoker = CallableInvoker(params=())

        assert invoker.invoke({}) == {}

    def test_builds_kwargs_from_available(self):
        params = (InjectionParam(name="value", source_type=SourceA, target_type=SourceA, extractor=identity),)
        invoker = CallableInvoker(params=params)

        source = SourceA()
        kwargs = invoker.invoke({SourceA: source})

        assert kwargs == {"value": source}

    def test_builds_kwargs_for_multiple_params_and_sources(self):
        params = (
            InjectionParam(name="a", source_type=SourceA, target_type=SourceA, extractor=identity),
            InjectionParam(name="b", source_type=SourceB, target_type=SourceB, extractor=identity),
        )
        invoker = CallableInvoker(params=params)

        a_obj, b_obj = SourceA(), SourceB()
        kwargs = invoker.invoke({SourceA: a_obj, SourceB: b_obj})

        assert kwargs == {"a": a_obj, "b": b_obj}

    def test_applies_extractor(self):
        params = (
            InjectionParam(
                name="name",
                source_type=SourceA,
                target_type=str,
                extractor=lambda _src: "extracted",
            ),
        )
        invoker = CallableInvoker(params=params)

        kwargs = invoker.invoke({SourceA: SourceA()})

        assert kwargs == {"name": "extracted"}

    def test_missing_source_raises_key_error(self):
        params = (InjectionParam(name="value", source_type=SourceA, target_type=SourceA, extractor=identity),)
        invoker = CallableInvoker(params=params)

        with pytest.raises(KeyError):
            invoker.invoke({})

    def test_does_not_store_or_call_target(self):
        # CallableInvoker has no reference to any target callable - it only builds kwargs.
        invoker = CallableInvoker(params=())
        assert not hasattr(invoker, "target")
        assert not hasattr(invoker, "call")

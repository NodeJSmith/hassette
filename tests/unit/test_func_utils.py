"""Tests for callable_name() and callable_short_name() utility functions."""

import functools
from functools import partial

from hassette.utils.func_utils import callable_name, callable_short_name

# --- Test helpers ---


def plain_function() -> None:
    pass


async def async_plain_function() -> None:
    pass


class MyClass:
    def method(self) -> None:
        pass


class CallableClass:
    def __call__(self) -> None:
        pass


def _decorator(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return fn(*args, **kwargs)

    return wrapper


@_decorator
def decorated_function() -> None:
    pass


# --- callable_name tests ---


class TestCallableName:
    def test_plain_function(self) -> None:
        name = callable_name(plain_function)
        assert name.endswith("plain_function")
        assert "test_func_utils" in name

    def test_bound_method(self) -> None:
        obj = MyClass()
        name = callable_name(obj.method)
        assert "MyClass" in name
        assert name.endswith("method")

    def test_lambda(self) -> None:
        fn = lambda: None  # noqa: E731
        name = callable_name(fn)
        assert "<lambda>" in name

    def test_partial_single(self) -> None:
        fn = partial(plain_function)
        name = callable_name(fn)
        assert name.startswith("partial(")
        assert "plain_function" in name

    def test_partial_nested(self) -> None:
        """Nested partials: inspect.unwrap strips one layer, then partial branch wraps it."""
        fn = partial(partial(plain_function))
        name = callable_name(fn)
        assert "partial(" in name
        assert "plain_function" in name

    def test_callable_class_instance(self) -> None:
        obj = CallableClass()
        name = callable_name(obj)
        assert "CallableClass" in name
        assert "__call__" in name

    def test_inner_function(self) -> None:
        def local_inner() -> None:
            pass

        name = callable_name(local_inner)
        assert "local_inner" in name

    def test_decorated_function(self) -> None:
        """Decorated function with @wraps should resolve to the original name via inspect.unwrap()."""
        name = callable_name(decorated_function)
        assert "decorated_function" in name


# --- callable_short_name tests ---


class TestCallableShortName:
    def test_default_num_parts(self) -> None:
        """num_parts=1 returns the last segment."""
        short = callable_short_name(plain_function)
        assert short == "plain_function"

    def test_num_parts_two(self) -> None:
        """num_parts=2 returns the last two dot-separated segments."""
        short = callable_short_name(plain_function, num_parts=2)
        parts = short.split(".")
        assert len(parts) == 2
        assert parts[-1] == "plain_function"

    def test_num_parts_exceeds_total(self) -> None:
        """When num_parts exceeds the number of segments, the full name is returned."""
        full = callable_name(plain_function)
        total_parts = len(full.split("."))
        short = callable_short_name(plain_function, num_parts=total_parts + 5)
        assert short == full

    def test_bound_method_default(self) -> None:
        obj = MyClass()
        short = callable_short_name(obj.method)
        assert short == "method"

    def test_bound_method_two_parts(self) -> None:
        obj = MyClass()
        short = callable_short_name(obj.method, num_parts=2)
        assert short == "MyClass.method"

    def test_lambda_default(self) -> None:
        fn = lambda: None  # noqa: E731
        short = callable_short_name(fn)
        assert "<lambda>" in short

    def test_callable_class_default(self) -> None:
        obj = CallableClass()
        short = callable_short_name(obj)
        assert short == "__call__"

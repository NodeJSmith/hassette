"""Tests for TaskBucket ownership invariants in Resource.__init__.

Pins three behaviors:
- A non-TaskBucket Resource gets its own TaskBucket (default factory path).
- A TaskBucket is its own task_bucket (is_task_bucket marker path).
- Constructing a Resource when the factory is unregistered raises RuntimeError.
"""

import pytest

from hassette.resources.base import Resource
from hassette.task_bucket import TaskBucket
from hassette.test_utils import make_mock_hassette

from .conftest import ConcreteResource


def test_non_task_bucket_resource_gets_own_bucket() -> None:
    """A non-TaskBucket Resource receives a freshly-created TaskBucket."""
    hassette = make_mock_hassette()
    resource = ConcreteResource(hassette=hassette)

    assert isinstance(resource.task_bucket, TaskBucket)
    assert resource.task_bucket is not resource


def test_task_bucket_is_its_own_bucket() -> None:
    """A TaskBucket is its own task_bucket (the is_task_bucket ClassVar path)."""
    hassette = make_mock_hassette()
    bucket = TaskBucket(hassette=hassette)

    assert bucket.task_bucket is bucket


def test_resource_without_factory_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Constructing a non-TaskBucket Resource with no registered factory raises RuntimeError."""
    monkeypatch.setattr(Resource, "_default_task_bucket_factory", None)
    hassette = make_mock_hassette()
    with pytest.raises(RuntimeError, match=r"hassette\.task_bucket"):
        ConcreteResource(hassette=hassette)

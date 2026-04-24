"""Integration tests for resource dependency ordering."""

from typing import TYPE_CHECKING

from hassette import Hassette

if TYPE_CHECKING:
    from hassette.resources.base import Resource


async def test_shutdown_order_is_reverse_init_order(hassette_instance: Hassette) -> None:
    """_ordered_children_for_shutdown returns instances in reverse _init_order type sequence."""
    shutdown_order: list[Resource] = hassette_instance._ordered_children_for_shutdown()
    init_order: list[type[Resource]] = hassette_instance._init_order

    type_to_instance = {type(c): c for c in hassette_instance.children}
    expected = [type_to_instance[t] for t in reversed(init_order) if t in type_to_instance]

    assert shutdown_order == expected, (
        f"Shutdown order types {[type(r).__name__ for r in shutdown_order]} "
        f"do not match reverse init order {[type(r).__name__ for r in expected]}"
    )


async def test_shutdown_order_covers_all_children(hassette_instance: Hassette) -> None:
    """_ordered_children_for_shutdown covers exactly the same set as children."""
    shutdown_order = hassette_instance._ordered_children_for_shutdown()
    assert set(shutdown_order) == set(hassette_instance.children), "Shutdown order must include every registered child"


async def test_shutdown_order_has_no_duplicates(hassette_instance: Hassette) -> None:
    """_ordered_children_for_shutdown contains each child instance at most once."""
    shutdown_order = hassette_instance._ordered_children_for_shutdown()
    assert len(shutdown_order) == len({id(r) for r in shutdown_order}), "Shutdown order must not contain duplicates"

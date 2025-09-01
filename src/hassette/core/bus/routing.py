from fnmatch import fnmatch

from .listeners import Listener

GLOB_CHARS = "*?["


def add_route(
    exact: dict[str, list[Listener]],
    globs: dict[str, list[Listener]],
    key: str,
    listener: Listener,
) -> None:
    """Add a listener to the appropriate route based on whether it contains glob characters.

    Args:
        exact (dict[str, list[Listener]]): Dictionary for exact matches.
        globs (dict[str, list[Listener]]): Dictionary for glob matches.
        key (str): The topic or key to add the listener to.
        L (Listener): The listener to add.

    """
    if any(ch in key for ch in GLOB_CHARS):
        globs.setdefault(key, []).append(listener)
    else:
        exact.setdefault(key, []).append(listener)


def remove_route(
    exact: dict[str, list[Listener]],
    globs: dict[str, list[Listener]],
    key: str,
    predicate,
) -> None:
    """Remove a listener from the appropriate route based on whether it contains glob characters.

    Args:
        exact (dict[str, list[Listener]]): Dictionary for exact matches.
        globs (dict[str, list[Listener]]): Dictionary for glob matches.
        key (str): The topic or key to remove the listener from.
        predicate (callable): A function that returns True for listeners to be removed."""
    bucket = globs if any(ch in key for ch in GLOB_CHARS) else exact
    if key in bucket:
        bucket[key] = [L for L in bucket[key] if not predicate(L)]
        if not bucket[key]:
            bucket.pop(key, None)


def matching_listeners(
    exact: dict[str, list[Listener]],
    globs: dict[str, list[Listener]],
    topic: str,
) -> list[Listener]:
    """Get all listeners that match the given topic.

    Args:
        exact (dict[str, list[Listener]]): Dictionary for exact matches.
        globs (dict[str, list[Listener]]): Dictionary for glob matches.
        topic (str): The topic to match against.

    Returns:
        list[Listener]: A list of listeners that match the topic.
    """
    out: list[Listener] = []
    out.extend(exact.get(topic, ()))

    for k, lst in globs.items():
        if fnmatch(topic, k):
            out.extend(lst)

    # de-dup preserving order
    seen, unique = set(), []
    for listener in out:
        if id(listener) not in seen:
            seen.add(id(listener))
            unique.append(listener)
    return unique

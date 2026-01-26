"""Utility functions for Home Assistant.

These have been copied from HA to ensure we use the same logic."""

import functools
import re

MAX_EXPECTED_ENTITY_IDS = 16384
_OBJECT_ID = r"(?!_)[\da-z_]+(?<!_)"
_DOMAIN = r"(?!.+__)" + _OBJECT_ID
VALID_DOMAIN = re.compile(r"^" + _DOMAIN + r"$")
VALID_ENTITY_ID = re.compile(r"^" + _DOMAIN + r"\." + _OBJECT_ID + r"$")


@functools.lru_cache(MAX_EXPECTED_ENTITY_IDS)
def split_entity_id(entity_id: str) -> tuple[str, str]:
    """Split a state entity ID into domain and object ID."""
    domain, _, object_id = entity_id.partition(".")
    if not domain or not object_id:
        raise ValueError(f"Invalid entity ID {entity_id}")
    return domain, object_id


@functools.lru_cache(64)
def valid_domain(domain: str) -> bool:
    """Test if a domain a valid format."""
    return VALID_DOMAIN.match(domain) is not None


@functools.lru_cache(512)
def valid_entity_id(entity_id: str) -> bool:
    """Test if an entity ID is a valid format.

    Format: <domain>.<entity> where both are slugs.
    """
    return VALID_ENTITY_ID.match(entity_id) is not None


@functools.lru_cache(512)
def extract_domain(entity_id: str) -> str:
    """Extract the domain from an entity ID."""
    domain, _ = split_entity_id(entity_id)
    return domain


def make_entity_id(entity_id: str, domain: str) -> str:
    """Ensure the entity_id has the correct domain prefix.

    If the entity_id already contains a domain prefix, validate that it matches the expected domain.

    Args:
        entity_id: The entity ID, with or without domain prefix.
        domain: The expected domain prefix (e.g., "light").

    Returns:
        The entity ID with the correct domain prefix.

    Raises:
        ValueError: If the entity_id has a domain prefix that does not match the expected domain.
    """
    if "." in entity_id:
        d, _ = split_entity_id(entity_id)
        if d != domain:
            raise ValueError(f"Entity ID '{entity_id}' has domain '{d}', expected '{domain}'.")
        if not valid_entity_id(entity_id):
            raise ValueError(f"Entity ID '{entity_id}' is not valid.")
        return entity_id

    output_entity_id = f"{domain}.{entity_id}"
    if not valid_entity_id(output_entity_id):
        raise ValueError(f"Generated entity ID '{output_entity_id}' is not valid.")
    return output_entity_id

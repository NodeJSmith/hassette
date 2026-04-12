import pytest

from hassette import TYPE_REGISTRY


class RGBColor:
    """Placeholder for a custom RGB color type."""

    red: int
    green: int
    blue: int


def test_custom_converter():
    """Test custom RGB converter."""
    # Valid conversion
    result = TYPE_REGISTRY.convert("255,128,0", RGBColor)
    assert result.red == 255
    assert result.green == 128
    assert result.blue == 0

    # Invalid format
    with pytest.raises(ValueError, match="Invalid RGB format"):
        TYPE_REGISTRY.convert("not_rgb", RGBColor)

    # Out of range
    with pytest.raises(ValueError, match="must be between 0 and 255"):
        TYPE_REGISTRY.convert("300,128,0", RGBColor)

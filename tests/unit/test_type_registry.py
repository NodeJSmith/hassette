from hassette import TYPE_REGISTRY


def test_type_already_in_desired_state_not_converted_again() -> None:
    """Test that a state already in the desired type is not converted again."""
    desired_value = 12.1
    desired_type = float

    output = TYPE_REGISTRY.convert(desired_value, desired_type)
    assert output == desired_value
    assert type(output) is desired_type


def test_type_conversion_idempotent() -> None:
    """Test that a state already in the desired type is not converted again."""
    original_value = "12.1"
    desired_value = 12.1
    desired_type = float

    output = TYPE_REGISTRY.convert(original_value, desired_type)
    assert output == desired_value
    assert type(output) is desired_type

    output_two = TYPE_REGISTRY.convert(output, desired_type)
    assert output_two == output
    assert type(output_two) is desired_type

"""Generates pydantic models from the incoming JSON data.

These will not be ready to use, but they are a decent starting point."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from datamodel_code_generator import DataModelType, InputFileType, generate
from datamodel_code_generator.format import Formatter

DEFAULT_FORMATTERS = [Formatter.RUFF_CHECK, Formatter.RUFF_FORMAT]


def generate_models(
    input_data: dict | list,
    output_file: str,
    aliases: dict[str, str] | None = None,
    class_name: str | None = None,
    special_field_name_prefix: str | None = None,
) -> None:
    with TemporaryDirectory() as temporary_directory_name:
        temporary_directory = Path(temporary_directory_name)
        output = Path(temporary_directory / "model.py")

        final_output = Path.cwd().joinpath(output_file)
        if not final_output.parent.exists():
            final_output.parent.mkdir(parents=True, exist_ok=True)
        if final_output.exists():
            final_output.unlink()
        output.touch()

        generate(
            json.dumps(input_data, indent=2, default=str),
            input_file_type=InputFileType.Json,
            output=output,
            output_model_type=DataModelType.PydanticV2BaseModel,
            snake_case_field=True,
            use_standard_collections=True,
            use_union_operator=True,
            use_schema_description=True,
            force_optional_for_required_fields=True,
            reuse_model=True,
            aliases=aliases,
            class_name=class_name,
            special_field_name_prefix=special_field_name_prefix,
            formatters=DEFAULT_FORMATTERS,
        )
        model: str = output.read_text()
        model_lines = model.splitlines()
        model_lines = [line for line in model_lines if not line.startswith("#")]
        model = "\n".join(model_lines)
        with final_output.open("w") as f:
            f.write(model)

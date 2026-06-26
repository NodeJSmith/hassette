from pydantic import Field

from hassette import AppConfig


class MyAppConfig(AppConfig):
    # ui hints control how each field renders in the dashboard Config tab.
    api_host: str = Field(
        default="localhost",
        json_schema_extra={"ui": {"label": "API Host", "order": 1}},
    )
    data_path: str = Field(
        default="/var/data",
        json_schema_extra={"ui": {"widget": "path", "order": 2}},
    )

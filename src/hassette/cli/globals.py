"""Global CLI state set by the meta app launcher, read by commands and make_client()."""

env_file_override: str | None = None
config_file_override: str | None = None
json_mode: bool = False

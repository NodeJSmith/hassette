"""AppRegistry mock factories for tests/unit/core/."""

from types import SimpleNamespace

from hassette.types.enums import ResourceStatus


def make_manifest_obj(  # factory-local: SimpleNamespace input shape for AppRegistry, not AppManifestInfo output
    app_key: str,
    enabled: bool = True,
    auto_loaded: bool = False,
    autostart: bool = True,
    app_config: dict | list[dict] | None = None,
) -> SimpleNamespace:
    """Build a minimal AppManifest-like object for the registry."""
    return SimpleNamespace(
        app_key=app_key,
        class_name=f"{app_key.title().replace('_', '')}",
        display_name=app_key.replace("_", " ").title(),
        filename=f"{app_key}.py",
        enabled=enabled,
        auto_loaded=auto_loaded,
        autostart=autostart,
        app_config=app_config if app_config is not None else {},
    )


def make_app_instance(  # factory-local: SimpleNamespace App stand-in for AppRegistry tests
    app_key: str, index: int = 0
) -> SimpleNamespace:
    """Build a minimal App-like object for the registry."""
    class_name = app_key.title().replace("_", "")
    instance_name = f"{app_key}.{index}"
    return SimpleNamespace(
        app_config=SimpleNamespace(instance_name=instance_name),
        class_name=class_name,
        status=ResourceStatus.RUNNING,
        unique_name=f"{class_name}.{instance_name}",
    )

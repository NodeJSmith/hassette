from hassette.resources.restart import RestartSpec
from hassette.resources.service import Service
from hassette.types.enums import RestartType


class MyService(Service):
    restart_spec = RestartSpec(
        restart_type=RestartType.TRANSIENT,
        budget_intensity=3,
        budget_period_seconds=120,
        fatal_error_names=("SchemaVersionError",),
    )

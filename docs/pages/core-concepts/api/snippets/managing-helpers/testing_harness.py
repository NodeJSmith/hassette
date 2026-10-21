from hassette.models.helpers import InputBooleanRecord
from hassette.testing import AppTestHarness

from myapp import VacationModeApp


async def test_vacation_mode_creates_helper_on_first_run():
    async with AppTestHarness(
        VacationModeApp, config={"instance_name": "vacation_mode_app"}
    ) as harness:
        records = await harness.api_recorder.helpers.list("input_boolean")
        assert len(records) == 1


async def test_list_returns_seeded_helper():
    async with AppTestHarness(
        VacationModeApp, config={"instance_name": "vacation_mode_app"}
    ) as harness:
        harness.seed_helper(
            InputBooleanRecord(
                id="vacation_mode", name="Vacation Mode", initial=False
            )
        )
        records = await harness.api_recorder.helpers.list("input_boolean")
        assert len(records) == 1
        assert records[0].name == "Vacation Mode"

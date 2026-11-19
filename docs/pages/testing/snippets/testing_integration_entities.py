from hassette.testing import AppTestHarness

from my_apps.cat_feeder import CatFeederApp


async def test_feeding_records_the_time():
    config = {"instance_name": "cat_feeder"}
    async with AppTestHarness(CatFeederApp, config=config) as harness:
        await harness.simulate_button_press("feed_now")
        assert harness.app.last_fed.value is not None

        await harness.simulate_switch_toggle("paused", True)
        assert harness.app.paused.is_on

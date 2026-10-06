from hassette_wire import WINDOWED_ACTIVITY_PARTS, AppActivity, requested_activity_parts


def test_windowed_requests_every_part() -> None:
    assert requested_activity_parts(windowed=True) == list(AppActivity.model_fields)


def test_unwindowed_requests_only_the_parts_that_need_no_window() -> None:
    parts = requested_activity_parts(windowed=False)

    assert parts
    assert not set(parts) & WINDOWED_ACTIVITY_PARTS
    assert set(parts) | WINDOWED_ACTIVITY_PARTS == set(AppActivity.model_fields)

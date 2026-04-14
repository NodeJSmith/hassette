from hassette.test_utils import create_call_service_event

event = create_call_service_event(
    domain="light",
    service="turn_on",
    service_data={"entity_id": "light.kitchen", "brightness": 200},
)

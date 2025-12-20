# Raw data from Home Assistant (untyped dict)
raw_data = {
    "entity_id": "light.bedroom",
    "state": "on",
    "attributes": {"brightness": 200, "color_temp": 370},
}

# After StateRegistry conversion (typed model)
# LightState(
#     entity_id="light.bedroom",
#     state="on",
#     attributes=LightAttributes(brightness=200, color_temp=370),
# )

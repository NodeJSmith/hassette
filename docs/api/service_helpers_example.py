from hassette import App


class ServiceHelpersExample(App):
    async def service_helpers_example(self):
        await self.api.call_service(
            "light",
            "turn_on",
            target={"entity_id": "light.porch"},
            brightness=80,
        )

        ctx = await self.api.turn_off("switch.air_purifier")
        self.logger.debug("Service request id=%s", ctx.id if ctx else "n/a")

        # Fire an automation event
        await self.api.fire_event("hassette_custom", {"trigger": "wake"})
        return ctx

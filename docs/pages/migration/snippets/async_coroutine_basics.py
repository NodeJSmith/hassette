from hassette import App


class MissingAwaitApp(App):
    # --8<-- [start:unawaited]
    async def on_motion(self):
        # Creates a coroutine object and throws it away.
        # The light never turns on. No error is raised.
        self.api.call_service(
            "light", "turn_on", target={"entity_id": "light.kitchen"}
        )
    # --8<-- [end:unawaited]


class CorrectAwaitApp(App):
    # --8<-- [start:awaited]
    async def on_motion(self):
        # await runs the coroutine to completion
        await self.api.call_service(
            "light", "turn_on", target={"entity_id": "light.kitchen"}
        )
    # --8<-- [end:awaited]

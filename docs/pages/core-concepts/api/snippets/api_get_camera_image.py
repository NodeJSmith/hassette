from hassette import App


class CameraApp(App):
    async def on_initialize(self):
        # Latest image
        image_bytes = await self.api.get_camera_image("camera.front_door")
        self.logger.info("Image size: %d bytes", len(image_bytes))

        # Image at a specific time
        snapshot_time = self.now().subtract(minutes=5)
        past_image = await self.api.get_camera_image(
            "camera.front_door",
            timestamp=snapshot_time,
        )
        self.logger.info("Past image size: %d bytes", len(past_image))

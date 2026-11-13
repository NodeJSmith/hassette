from hassette import App


class CameraApp(App):
    async def on_initialize(self):
        image_bytes = await self.api.get_camera_image("camera.front_door")
        self.logger.info("Image size: %d bytes", len(image_bytes))

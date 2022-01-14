
from simpleobsws import obsws

class OBSWebsocketExecutor:
    def __init__(self, port: int = 4444, password: str = None):
        self._ws = obsws(port=port, password=password)

    async def connect(self):
        await self._ws.connect()

    async def set_scene_item_visibility(self, source_name: str, visible: bool, scene_name: str = None):
        data = {'item': source_name, 'visible': visible}
        if scene_name is not None:
            data['scene-name'] = scene_name
        await self._ws.call('SetSceneItemProperties', data=data)

    async def update_source_settings(self, source_name: str, new_settings: dict):
        currentSettings = await self._ws.call('GetSourceSettings', data={'sourceName': source_name})
        currentSettings.update(new_settings)
        await self._ws.call('SetSourceSettings', data={'sourceName': source_name, 'sourceSettings': currentSettings})

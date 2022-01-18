
import simpleobsws

class OBSWebsocketExecutor:
    def __init__(self, port: int = 4444, password: str = None):
        if password is None:
            password = ''
        ident_params = simpleobsws.IdentificationParameters(ignoreNonFatalRequestChecks=True)
        ident_params.eventSubscriptions = (1 << 0) | (1 << 2) 
        self._ws = simpleobsws.WebSocketClient(
            url=f'ws://localhost:{port}',
            password=password,
            identification_parameters=ident_params
        )

    async def connect(self):
        try:
            if not await self._ws.connect():
                return False
        except OSError:
            return False
        return await self._ws.wait_until_identified(30)

    async def disconnect(self):
        await self._ws.disconnect()

    async def set_scene_item_visibility(self, scene_name: str, source_name: str, visible: bool) -> bool:
        # TODO: update to use GetSceneItemId
        ret = await self._ws.call(simpleobsws.Request('GetSceneItemList', {'sceneName': scene_name}))
        if not ret.ok():
            return False
        source_id = -1
        for item in ret.responseData['sceneItems']:
            if item['sourceName'] == source_name:
                source_id = item['sceneItemId']
                break
        if source_id == -1:
            return False
        data = {'sceneName': scene_name, 'sceneItemId': source_id, 'sceneItemEnabled': visible}
        request = simpleobsws.Request('SetSceneItemEnabled', data)
        ret = await self._ws.call(request)
        return ret.ok()


    async def update_source_settings(self, source_name: str, new_settings: dict) -> bool:
        # TODO: update to new protocol, if possible
        get_settings_request = simpleobsws.Request('GetSourceSettings', {'sourceName': source_name})
        ret = await self._ws.call(get_settings_request)
        if not ret.ok():
            return False
        current_settings = ret.responseData
        current_settings.update(new_settings)
        request = simpleobsws.Request(
            'SetSourceSettings',
            data={'sourceName': source_name, 'sourceSettings': current_settings}
        )
        ret = await self._ws.call(request)
        return ret.ok()


from obs_websocket_executor import OBSWebsocketExecutor
import asyncio

e = OBSWebsocketExecutor(password='thisisatest')

async def to_run(executor: OBSWebsocketExecutor):
    await executor.connect()
    print(await executor.set_scene_item_visibility('Scene', 'Chat', True))


loop = asyncio.get_event_loop()
loop.run_until_complete(to_run(e))

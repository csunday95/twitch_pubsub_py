
from concurrent.futures import CancelledError
from typing import List, Callable, Optional, Dict
import websockets
from websockets import client as wsclient
from websockets.client import WebSocketClientProtocol
import json
import asyncio
import inspect

TWITCH_WEBSOCKET_URI = 'wss://pubsub-edge.twitch.tv'
PONG_TIMEOUT = 10
WS_CLOSE_TIMEOUT = 1


class TwitchPubSubClient:
    def __init__(self, topics: List[str], auth_token: str, broadcaster_id: str, callbacks: Dict[str, Callable[[dict, List[int]], None]], heartbeat_rate: float = 60):
        self._topics = topics
        self._auth_token = auth_token
        self._broadcaster_id = broadcaster_id
        self._asyncio_loop = None
        self._connection = None  # type: Optional[WebSocketClientProtocol]
        self._callbacks = callbacks
        self._heartbeat_rate = heartbeat_rate if heartbeat_rate >= 20 else 20 # set 20 as minimum 
        self._heartbeat_event = asyncio.Event()
        self._heartbeat_abort = asyncio.Event()
        self._callback_queue = asyncio.Queue()
        self._callback_task = None  # type: asyncio.Task
        self._heartbeat_task = None  # type: asyncio.Task
        self._receive_task = None  # type: asyncio.Task

    async def _connect(self):
        self._connection = await wsclient.connect(TWITCH_WEBSOCKET_URI, close_timeout=WS_CLOSE_TIMEOUT)
        if not self._connection.open:
            self._connection = None
            print('unable to connect to twitch pubsub endpoint')
            return False
        subscription_data = {
            'type': 'LISTEN',
            'data': {
                'topics': [t.format(channel_id=self._broadcaster_id) for t in self._topics],
                'auth_token': self._auth_token
            }
        }
        await self._connection.send(json.dumps(subscription_data))
        resp = json.loads(await self._connection.recv())
        if 'error' in resp and len(resp['error']) > 0:
            await self._connection.close()
            self._connection = None
            print('Got error subscribing on pubsub endpoint')
            return False
        self._callback_task = asyncio.create_task(self._process_callbacks(self._callback_queue))
        return True

    def disconnect(self):
        if self._asyncio_loop is not None:
            fut = asyncio.run_coroutine_threadsafe(self._disconnect_async(), self._asyncio_loop)
            try:
                fut.result()
            except (asyncio.CancelledError, CancelledError):
                print('disconnect future cancelled')

    async def _disconnect_async(self):
        print('here')
        if self._callback_task is not None:
            self._callback_queue.put_nowait((None, None, None))
        if self._heartbeat_task is not None:
            self._heartbeat_abort.set()
            self._heartbeat_event.set()
        try:
            if self._connection is not None and self._connection.open:
                print('about to close')
                await self._connection.close()
                self._connection = None
            print('closed')
            to_wait = [self._callback_task, self._receive_task, self._heartbeat_task]
            to_wait = [t for t in to_wait if t is not None]
            if len(to_wait) > 0:
                await asyncio.wait(to_wait)
            # print('about to gather')
            # await asyncio.gather(self._callback_task, return_exceptions=True)
            # print('past callback')
            # # TODO: heartbeat task is never exiting
            # await asyncio.gather(self._heartbeat_task, return_exceptions=True)
            # print('past heartbeat')
            # await asyncio.gather(self._receive_task, return_exceptions=True)
            print('past wait')

        except asyncio.CancelledError as e:
            print('?')
        except Exception as e:
            print('huh?')
        finally:
            self._asyncio_loop = None
            self._receive_task = None
            self._callback_task = None
            self._heartbeat_task = None

    async def _process_callbacks(self, queue: asyncio.Queue):
        while True:
            callback, data, user_ids = await queue.get()
            if callback is None:
                queue.task_done()
                return
            if inspect.iscoroutinefunction(callback):
                await callback(data, user_ids)
            else:
                callback(data, user_ids)
            queue.task_done()

    async def _heartbeat(self):
        self._heartbeat_abort.clear()
        to_send = json.dumps({'type': 'PING'})
        while not self._heartbeat_task.cancelled():
            try:
                self._heartbeat_event.clear()
                await self._connection.send(to_send)
                try:
                    await asyncio.wait_for(self._heartbeat_event.wait(), PONG_TIMEOUT)
                except asyncio.TimeoutError:
                    print('exited heartbeat loop due to pong timeout')
                    return
                try:
                    await asyncio.wait_for(self._heartbeat_abort.wait(), self._heartbeat_rate)
                    print('exiting heartbeat after heartbeat abort and cancelled task')
                    return
                except asyncio.TimeoutError:
                    pass
            except asyncio.CancelledError:
                print(f'exited heartbeat loop due to disconnect')
                return
    
    async def _reconnect(self, max_tries: int = -1):
        wait_time = 1
        tries = 0
        if max_tries < 0:
            max_tries = float('inf')
        await self._disconnect_async()
        while not await self._connect() and tries < max_tries:
            print(f'failed on reconnect; attempting again in {wait_time} seconds')
            await asyncio.sleep(wait_time)
            wait_time *= 2  # exponential backoff
            tries += 1
        if max_tries < 0:
            return True
        else:
            return tries < max_tries

    async def _receive_loop(self):
        try:
            async for event in self._connection:
                event = json.loads(event)
                if 'type' not in event:
                    print('got improperly formatted event')
                    continue
                event_type = event['type']
                if event_type == 'RECONNECT':
                    print('Got explicit reconnect message from twitch; reconnecting...')
                    await self._reconnect()
                elif event_type == 'MESSAGE':
                    try:
                        data = event['data']
                        topic = data['topic']
                        user_ids = []
                        while '.' in topic:
                            topic, _, user_id = topic.partition('.')
                            user_ids.append(int(user_id))
                    except (KeyError, ValueError) as e:
                        print(f'malformed message from twitch: {e}')
                        continue
                    if topic in self._callbacks:
                        self._callback_queue.put_nowait((self._callbacks[topic], json.loads(data['message']), user_ids))
                elif event_type == 'PONG':
                    self._heartbeat_event.set()
                else:
                    print(f'Encountered unknown message type {event_type}: {event}')
        except websockets.exceptions.ConnectionClosed as e:
            print('exited receive loop due to disconnect')
            return
    
    async def run_tasks(self, reconnect_retries: int = 6):
        if not await self._connect():
            return 'Unable to connect to twitch PubSub endpoint'
        self._asyncio_loop = asyncio.get_running_loop()
        self._heartbeat_task = asyncio.ensure_future(self._heartbeat())
        self._receive_task = asyncio.ensure_future(self._receive_loop())
        tasks = [self._heartbeat_task, self._receive_task]
        while True:
            _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if self._heartbeat_abort.is_set():
                break
            if self._receive_task in pending:  # heartbeat failure case
                print('failed heartbeat check; attempting to reconnect')
                if not await self._reconnect(max_tries=reconnect_retries):
                    print('unable to reconnect, exiting')
                    self._disconnect()
                    for task in pending:
                        asyncio.wait([task])
                    return 'Unable to reconnect to twitch PubSub endpoint'
                tasks = [
                    self._receive_task,
                    asyncio.ensure_future(self._heartbeat())
                ]
            else:  # receive task failure case
                break
        return None
        


from typing import List, Callable, Optional, Dict
import websockets
from websockets import client as wsclient
from websockets.client import WebSocketClientProtocol
import json
from obswebsocket import obsws
from obswebsocket import requests as obsrequests
import asyncio

TWITCH_WEBSOCKET_URI = 'wss://pubsub-edge.twitch.tv'
PONG_TIMEOUT = 10


class TwitchPubSubClient:
    def __init__(self, topics: List[str], auth_token: str, broadcaster_id: str, callbacks: Dict[str, Callable[[dict, List[int]], None]], heartbeat_rate: float = 60):
        self._topics = topics
        self._auth_token = auth_token
        self._broadcaster_id = broadcaster_id
        self._connection = None  # type: Optional[WebSocketClientProtocol]
        self._callbacks = callbacks
        self._heartbeat_rate = heartbeat_rate if heartbeat_rate >= 20 else 20 # set 20 as minimum 
        self._heartbeat_event = asyncio.Event()

    async def _connect(self):
        self._connection = await wsclient.connect(TWITCH_WEBSOCKET_URI)
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
            self._connection.close()
            self._connection = None
            print('Got error subscribing on pubsub endpoint')
            return False
        return True

    async def _disconnect(self):
        if self._connection is not None and self._connection.open:
            await self._connection.close()
            self._connection = None

    async def _heartbeat(self):
        while True:
            try:
                to_send = json.dumps({'type': 'PING'})
                self._heartbeat_event.clear()
                await self._connection.send(to_send)
                try:
                    await asyncio.wait_for(self._heartbeat_event.wait(), PONG_TIMEOUT)
                except asyncio.TimeoutError:
                    print('exited heartbeat loop due to pong timeout')
                    return
                await asyncio.sleep(self._heartbeat_rate)
            except websockets.exceptions.ConnectionClosed:
                print('exited heartbeat loop due to disconnect')
                return 
    
    async def _reconnect(self, max_tries: int = -1):
        wait_time = 1
        tries = 0
        if max_tries < 0:
            max_tries = float('inf')
        await self._disconnect()
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
                        self._callbacks[topic](json.loads(data['message']), user_ids)
                elif event_type == 'PONG':
                    self._heartbeat_event.set()
                else:
                    print(f'Encountered unknown message type {event_type}: {event}')
        except websockets.exceptions.ConnectionClosed as e:
            print('exited receive loop due to disconnect')
            return
    
    async def run_tasks(self, reconnect_retries: int = 6):
        if not await self._connect():
            print('Unable to connect to twitch PubSub endpoint')
            return 1
        heartbeat_task = asyncio.ensure_future(self._heartbeat())
        receive_task = asyncio.ensure_future(self._receive_loop())
        tasks = [heartbeat_task, receive_task]
        while True:
            _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if receive_task in pending:  # heartbeat failure case
                print('failed heartbeat check; attempting to reconnect')
                if not await self._reconnect(max_tries=reconnect_retries):
                    print('unable to reconnect, exiting')
                    self._disconnect()
                    for task in pending:
                        asyncio.wait([task])
                    return
                tasks = [
                    receive_task,
                    asyncio.ensure_future(self._heartbeat())
                ]
        

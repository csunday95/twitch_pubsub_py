
from typing import Callable, Dict, List
from obs_websocket_executor import OBSWebsocketExecutor
from actions import Action

class TwitchWebsocketEventCallbacks:
    def __init__(self, ws_executor: OBSWebsocketExecutor, 
                 channel_points_redemption_actions: Dict[str, List[Action]],
                 log_callback: Callable[[str,], None]):
        self._ws_executor = ws_executor
        self._channel_points_redemption_actions = channel_points_redemption_actions
        self._log_callback = log_callback

    async def connect(self):
        return await self._ws_executor.connect()

    async def handle_redemption_reward(self, reward: dict, user_ids: List[int]):
        reward = reward['data']['redemption']['reward']
        reward_title = reward['title']
        if reward_title in self._channel_points_redemption_actions:
            self._log_callback(f'Execution action for {reward_title}')
            for action in self._channel_points_redemption_actions[reward_title]:
                await action.execute(self._ws_executor)
    
    def list_callbacks(self):
        return {
            'channel-points-channel-v1': self.handle_redemption_reward
        }
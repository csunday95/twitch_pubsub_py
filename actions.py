
from typing import Dict, List
from enum import Enum
import json
from obs_websocket_executor import OBSWebsocketExecutor
import asyncio


class ActionEnum(Enum):
    SetSceneItemVisibility = "set_scene_item_visibility"
    UpdateSourceSettings = "update_source_settings"
    Wait = "wait"

class Action:
    def __init__(self, action_type: ActionEnum, args: list):
        self._action_type = action_type
        self._args = args

    @staticmethod
    def parse_actions_from_file(actions_file) -> Dict[str, List['Action']]:
        with open(actions_file) as a_file:
            return Action.parse_actions(json.load(a_file))
    
    @staticmethod
    def parse_actions(actions_obj: dict):
        actions_dict = {}
        for redemption_name, action_spec_list in actions_obj.items():
            if not isinstance(action_spec_list, list):
                raise ValueError('Action specs must be a list')
            action_spec_entries = []
            for entry in action_spec_list:
                action_spec_entries.append(
                    Action(ActionEnum(entry['name']), entry['args'])
                )
            actions_dict[redemption_name] = action_spec_entries
        return actions_dict

    async def execute(self, ws_executor: OBSWebsocketExecutor):
        if self._action_type == ActionEnum.SetSceneItemVisibility:
            await ws_executor.set_scene_item_visibility(*self._args)
        elif self._action_type == ActionEnum.UpdateSourceSettings:
            await ws_executor.update_source_settings(*self._args)
        elif self._action_type == ActionEnum.Wait:
            await asyncio.sleep(float(self._args[0]))
        else:
            raise ValueError(f'Unknown action type {self._action_type}')

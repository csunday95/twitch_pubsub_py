
from typing import List, Dict, Callable
import os
import asyncio
import sys
import argparse
import webbrowser
import multiprocessing
import json
from auth_management_server import run_auth_server
from helix_api_manager import HelixAPIManager
from aiohttp import web
from twitch_pub_sub_client import TwitchPubSubClient
from obs_websocket_executor import OBSWebsocketExecutor
from actions import Action
from PyQt5.QtWidgets import QApplication
from redemption_obs_main_window import RedemptionOBSMainWindow
from twitch_websocket_event_callbacks import TwitchWebsocketEventCallbacks

# future plan: use to make a font nap prevention mechanism?
# proc on ban of a fontNap alt account

__version__ = '0.1.0'
TOPICS = ["channel-points-channel-v1.{channel_id}"]


def handle_twitch_auth(client_id):
    print('initializing auth redirect server')
    app = web.Application()
    mp_queue = multiprocessing.Queue()
    http_server_handle = multiprocessing.Process(target=run_auth_server,
                                                 args=(app, mp_queue, ),
                                                 daemon=True)
    http_server_handle.start()
    authorization_url = 'https://id.twitch.tv/oauth2/authorize'
    authorization_url += '?response_type=token'
    authorization_url += '&client_id={client_id}'.format(client_id=client_id)
    authorization_url += '&redirect_uri={redirect}'.format(redirect='http://localhost:8000')
    authorization_url += '&scope=channel:read:redemptions'
    webbrowser.open(authorization_url, new=2)
    access_token = mp_queue.get()
    http_server_handle.terminate()
    http_server_handle.join()
    print('Authentication process complete, closing redirect server and starting redemption monitoring')
    return access_token

async def run_websocket_tasks(auth_token, broadcaster_id, config: dict, 
                              actions_dict: Dict[str, List[Action]]):
    obsExecutor = OBSWebsocketExecutor(
        port=config.get('obsws_port', 4444),
        password=config.get('obsws_password', '')
    )
    if not await obsExecutor.connect():
        print('Unable to connect to OBS! ensure it is running and has OBS Websocket active')
        return
    callbackObj = TwitchWebsocketEventCallbacks(
        obsExecutor, 
        actions_dict
    )
    pubsub_client = TwitchPubSubClient(TOPICS, auth_token, broadcaster_id, callbackObj.list_callbacks(), heartbeat_rate=1)
    await pubsub_client.run_tasks()


def bootstrap(config: dict, actions_dict: dict, log_callback: Callable[[str,], None]):
    auth_token = handle_twitch_auth(config['client_id'])
    broadcaster_name = config['broadcaster_name']
    with HelixAPIManager(client_id=config['client_id'], user_token=auth_token) as manager:
        broadcaster_id = manager.get_user_id_by_username(broadcaster_name)
        log_callback(f'Got broadcaster ID {broadcaster_id} for user {broadcaster_name}')
    asyncio.run(run_websocket_tasks(auth_token, broadcaster_id, config, actions_dict))


def main(args):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'configuration_file_path',
        help='the path to the configuration file to use',
        default='config.json',
        nargs='?'
    )
    result = vars(parser.parse_args(args))
    print(f'starting Twitch Channel Point Monitor {__version__}')
    config_file_path = result['configuration_file_path']
    if not os.path.isfile(config_file_path):
        print(f'Configuration file {config_file_path} does not exist.')
        return 1
    # with open(config_file_path, 'r') as config_file:
    #     config = json.load(config_file)  # TODO: handle error on bad formatting

    # if isinstance(config['actions'], str):
    #     # TODO: handle error on bad formatting here
    #     actions_dict = Action.parse_actions_from_file(config['actions'])
    # else:
    #     actions_dict = Action.parse_actions(config['actions'])

    app = QApplication([])
    main_window = RedemptionOBSMainWindow(config_file_path)
    main_window.show()
    app.exec_()

    # bootstrap(config, actions_dict)
    return 0

if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

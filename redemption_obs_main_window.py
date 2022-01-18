
from typing import Optional, Dict, List
from threading import Thread
import multiprocessing
import webbrowser
from aiohttp import web
import json
import asyncio
from PyQt5.QtWidgets import QMainWindow, QWidget, QGridLayout, \
        QGroupBox, QVBoxLayout, QLineEdit, QHBoxLayout, QLabel, \
        QPushButton, QTextEdit, QComboBox
from PyQt5.QtGui import QIntValidator, QCloseEvent
from PyQt5.QtCore import pyqtSignal
from actions import Action
from twitch_pub_sub_client import TwitchPubSubClient
from obs_websocket_executor import OBSWebsocketExecutor
from auth_management_server import run_auth_server
from twitch_websocket_event_callbacks import TwitchWebsocketEventCallbacks
from helix_api_manager import HelixAPIManager

DEFAULT_OBS_WS_PORT = '4444'
TWITCH_AUTH_TOPICS = ["channel-points-channel-v1.{channel_id}"]
TWITCH_CLIENT_ID = 'piho0ccplzihr1aywpzjv4x79b2wrc'


class RedemptionOBSMainWindow(QMainWindow):
    _add_log_message_signal = pyqtSignal(str)
    _load_configuration_complete_signal = pyqtSignal(object, object)
    _connection_complete_signal = pyqtSignal(bool)
    _disconnect_complete_signal = pyqtSignal()
    _action_run_test_complete_signal = pyqtSignal()
    def __init__(self, config_file_path: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._config_file_path = config_file_path
        self._config = {
            "broadcaster_name": "",
            "client_id": "piho0ccplzihr1aywpzjv4x79b2wrc",
            "actions": "actions.json",
            "obsws_password": "password",
            "obsws_port": 4444
        }
        self._actions_dict = {}
        self._connect_thread = None  # type: Thread
        self._disconnect_thread = None  # type: Thread
        self._test_action_thread = None  # type: Thread
        self._is_connected = False
        self._obs_executor = None  # type: OBSWebsocketExecutor
        self._event_callback_obj = None  # type: TwitchWebsocketEventCallbacks
        self._pubsub_client = None  # type: TwitchPubSubClient
        self._async_loop = None
        self.setWindowTitle('Twitch Redemption OBS Manager')
        self._status_bar = self.statusBar()
        self._status_bar.showMessage('Not Connected')
        self._central_widget = QWidget()
        self._main_layout = QGridLayout()
        self._central_widget.setLayout(self._main_layout)
        self.setCentralWidget(self._central_widget)
        self._connect_button = QPushButton('Connect')
        self._connect_button.setDisabled(True)
        self._main_layout.addWidget(self._connect_button, 0, 0, 1, 2)
        self._config_group_box = QGroupBox('Configuration')
        self._main_layout.addWidget(self._config_group_box, 1, 0)
        self._config_layout = QGridLayout()
        self._config_group_box.setLayout(self._config_layout)
        self._broadcaster_name_line_edit = QLineEdit()
        self._port_line_edit = QLineEdit(str(self._config['obsws_port']))
        self._port_line_edit.setValidator(QIntValidator(1000, 2**16 - 1, self._port_line_edit))
        self._password_line_edit = QLineEdit(self._config['obsws_password'])
        self._password_line_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._config_layout.addWidget(QLabel('Broadcaster Name:'), 0, 0)
        self._config_layout.addWidget(self._broadcaster_name_line_edit, 0, 1)
        self._config_layout.addWidget(QLabel('Port:'), 1, 0)
        self._config_layout.addWidget(self._port_line_edit, 1, 1)
        self._config_layout.addWidget(QLabel('Password:'), 2, 0)
        self._config_layout.addWidget(self._password_line_edit, 2, 1)
        self._log_text_edit = QTextEdit()
        self._log_text_edit.setReadOnly(True)
        self._log_group_box = QGroupBox('Message Log')
        self._log_layout = QVBoxLayout()
        self._log_layout.addWidget(self._log_text_edit)
        self._log_group_box.setLayout(self._log_layout)
        self._main_layout.addWidget(self._log_group_box, 1, 1)
        self._tester_group_box = QGroupBox('Action Tester')
        tester_layout = QHBoxLayout()
        tester_layout.addWidget(QLabel('Redemption Name:'))
        self._tester_redemption_name_cbox = QComboBox()
        self._tester_redemption_name_cbox.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents
        )
        tester_layout.addWidget(self._tester_redemption_name_cbox)
        self._tester_run_button = QPushButton('Run')
        self._tester_run_button.setDisabled(True)
        tester_layout.addWidget(self._tester_run_button)
        tester_layout.addStretch()
        self._tester_group_box.setLayout(tester_layout)
        self._main_layout.addWidget(self._tester_group_box, 2, 0, 1, 2)
        self._connect_button.clicked.connect(self._handle_connect_button_clicked)
        self._tester_run_button.clicked.connect(self._handle_tester_run_button_clicked)
        self._add_log_message_signal.connect(self._on_add_log_message)
        self._load_configuration_complete_signal.connect(self._handle_load_configuration_complete)
        self._connection_complete_signal.connect(self._handle_connection_complete)
        self._disconnect_complete_signal.connect(self._handle_disconnect_complete)
        self._action_run_test_complete_signal.connect(self._handle_action_run_test_complete)
        self._config_thread = Thread(target=self._load_configuration)
        self._config_thread.start()

    def closeEvent(self, a0: QCloseEvent) -> None:
        return super().closeEvent(a0)

    def _load_configuration(self):
        self.add_log_message(f'Loading config from {self._config_file_path}')
        with open(self._config_file_path, 'r') as config_file:
            try:
                config = json.load(config_file)  # TODO: handle error on bad formatting
            except json.JSONDecodeError as e:
                self.add_log_message(f'Unable to load saved config from {self._config_file_path}: {e}.')
                self.add_log_message('All configuration values will be set to default')
                self._load_configuration_complete_signal.emit(None, None)
                return
        actions_spec = config['actions']
        try:
            if isinstance(actions_spec, str):
                self.add_log_message(f'Loading actions from {actions_spec}')
                actions_dict = Action.parse_actions_from_file(actions_spec)
            else:
                actions_dict = Action.parse_actions(actions_spec)
        except json.JSONDecodeError as e:
            self.add_log_message(f'Unable to load actions from {actions_spec}: {e}')
            self.add_log_message(f'No actions will be available.')
            self._load_configuration_complete_signal.emit(config, None)
        self.add_log_message('Configuration and actions loaded!')
        self._load_configuration_complete_signal.emit(config, actions_dict)

    def _handle_load_configuration_complete(self, loaded_config: dict, loaded_actions: dict):
        if loaded_config is not None:
            self._config.update(loaded_config)
            self._set_config_ui_values()
        if loaded_actions is not None:
            self._actions_dict = loaded_actions
        self._connect_button.setDisabled(False)
        action_names = sorted(list(self._actions_dict.keys()))
        self._tester_redemption_name_cbox.addItems(action_names)
    
    def _set_config_ui_values(self):
        self._broadcaster_name_line_edit.setText(str(self._config['broadcaster_name']))
        self._port_line_edit.setText(str(self._config['obsws_port']))
        self._password_line_edit.setText(str(self._config['obsws_password']))
    
    def _handle_connect_button_clicked(self, _: bool):
        self._connect_button.setDisabled(True)
        if self._is_connected:
            self._status_bar.showMessage('Disconnecting...')
            Thread(target=self._disconnect_callback).start()
        else:
            self._status_bar.showMessage('Connecting...')
            self._connect_thread = Thread(target=self._connect_callback)
            self._connect_thread.start()

    def _handle_tester_run_button_clicked(self, _: bool):
        self._tester_run_button.setDisabled(True)
        self._tester_run_button.setText('Running...')
        self._tester_redemption_name_cbox.setDisabled(True)
        redemption_name = self._tester_redemption_name_cbox.currentText()
        self._test_action_thread = Thread(
            target=self._run_action_test_callback, args=(redemption_name,)
        )
        self._test_action_thread.start()

    def _run_action_test_callback(self, redemption_name: str):
        if self._async_loop is None or not self._is_connected:
            raise RuntimeError('Cannot run action tests while disconnected')
        redemption_obj = {
            'data': {
                'redemption': {
                    'reward': {
                        'title': redemption_name
                    }
                }
            }
        }
        fut = asyncio.run_coroutine_threadsafe(
            self._event_callback_obj.handle_redemption_reward(redemption_obj, []),
            self._async_loop
        )
        fut.result()

    def _handle_connection_complete(self, success: bool):
        if success:
            self._connect_button.setText('Disconnect')
            self._tester_run_button.setDisabled(False)
            self._status_bar.showMessage('Connected')
        else:
            self._status_bar.showMessage('Connection failed!')
        self._connect_button.setDisabled(False)
        self._connect_thread = None

    def _handle_disconnect_complete(self):
        self._connect_button.setText('Connect')
        self._connect_button.setDisabled(False)
        self._status_bar.showMessage('Not Connected')
        self._disconnect_thread = None
        self._async_loop = None

    def _handle_action_run_test_complete(self):
        self._tester_run_button.setDisabled(False)
        self._tester_run_button.setText('Run')
        self._tester_redemption_name_line_edit.setReadOnly(False)

    def add_log_message(self, message: str):
        self._add_log_message_signal.emit(message)

    def _on_add_log_message(self, message: str):
        self._log_text_edit.append(message + '\n')

    def _handle_twitch_auth(self, client_id):
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

    async def _run_websocket_tasks(self, auth_token, broadcaster_id):
        self._async_loop = asyncio.get_running_loop()
        self._obs_executor = OBSWebsocketExecutor(
            port=self._config['obsws_port'],
            password=self._config['obsws_password']
        )
        self.add_log_message('Connecting to OBS Websocket...')
        if not await self._obs_executor.connect():
            self.add_log_message('Unable to connect to OBS! ensure it is running and has OBS Websocket active.')
            self._connection_complete_signal.emit(False)
            return
        self.add_log_message('Connected!')
        self._event_callback_obj = TwitchWebsocketEventCallbacks(
            self._obs_executor, 
            self._actions_dict,
            self.add_log_message
        )
        self._pubsub_client = TwitchPubSubClient(
            TWITCH_AUTH_TOPICS, 
            auth_token, broadcaster_id, 
            self._event_callback_obj.list_callbacks(), 
            heartbeat_rate=20
        )
        self._is_connected = True
        self._connection_complete_signal.emit(True)
        self.add_log_message('Starting redemption monitoring...')
        err = await self._pubsub_client.run_tasks()
        if err is not None:
            self.add_log_message(f'Twitch PubSub client encountered an error: {err}')
        self.add_log_message('Exiting websocket task')


    def _connect_callback(self):
        if self._is_connected:
            return
        auth_token = self._handle_twitch_auth(self._config['client_id'])
        broadcaster_name = self._config['broadcaster_name']
        self.add_log_message('Getting broadcaster id...')
        with HelixAPIManager(client_id=self._config['client_id'], user_token=auth_token) as manager:
            broadcaster_id = manager.get_user_id_by_username(broadcaster_name)
            self.add_log_message(f'Got broadcaster ID {broadcaster_id} for user {broadcaster_name}')
        asyncio.run(self._run_websocket_tasks(auth_token, broadcaster_id))
        self.add_log_message('Clean exit complete')
        # now execute disconnect complete callback?

    def _disconnect_callback(self):
        if not self._is_connected:
            return
        self._pubsub_client.disconnect()
        self._is_connected = False
        self._disconnect_complete_signal.emit()

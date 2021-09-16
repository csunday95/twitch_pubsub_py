from typing import Optional
import requests


class HelixAPIManager:
    TWITCH_ID_URL = 'https://id.twitch.tv/oauth2/'
    TWITCH_API_URL = 'https://api.twitch.tv/helix/'
    REQUIRED_API_SCOPES = [
        'channel:read:subscriptions'
    ]

    def __init__(self, client_id: str, client_secret: str = None, user_token: str = None) -> None:
        self._client_id, self._client_secret = client_id, client_secret
        self._user_token = user_token
        self._auth_token = None
        self._api_session = requests.Session()

    def _client_credential_oauth_flow(self):
        resp = requests.post(
            self.TWITCH_ID_URL + 'token',
            params={
                'client_id': self._client_id,
                'client_secret': self._client_secret,
                'grant_type': 'client_credentials',
                'scope': ' '.join(self.REQUIRED_API_SCOPES)
            }
        )
        if not resp.ok:
            raise RuntimeError('Unable to acquire token: {}'.format(resp.text))
        resp = resp.json()
        try:
            self._auth_token = resp['access_token']
        except KeyError:
            raise RuntimeError('Twitch authentication response did not contain access_token')
        self._api_session.headers.update({
            'Client-ID': self._client_id,
            'Authorization': f'Bearer {self._auth_token}'
        })
        return self

    def _implicit_code_oauth_flow(self):
        self._auth_token = self._user_token
        self._api_session.headers.update({
            'Client-ID': self._client_id,
            'Authorization': f'Bearer {self._auth_token}'
        })
        return self

    def __enter__(self):
        if self._client_secret is not None:
            return self._client_credential_oauth_flow()
        elif self._user_token is not None:
            return self._implicit_code_oauth_flow()
        raise RuntimeError('Either client credentials or user token myst be specified')

    def __exit__(self, type, value, traceback):
        if self._user_token is None:
            revoke_resp = requests.post(
                self.TWITCH_ID_URL + 'revoke',
                params={'client_id': self._client_id, 'token': self._auth_token}
            )
            if not revoke_resp.ok:
                raise RuntimeError('Unable to revoke token on exit: {}'.format(revoke_resp.status_code))
        self._auth_token = None

    def get_user_id_by_username(self, username: str) -> Optional[str]:
        if self._auth_token is None:
            raise RuntimeError('API Manager has not received an auth token')
        resp = self._api_session.get(
            self.TWITCH_API_URL + 'users',
            params={'login': username}
        )
        if not resp.ok:
            raise RuntimeError('Got Error response from twitch: {}'.format(resp.status_code))
        user_info = resp.json()['data'][0]
        return user_info['id']

    def get_subscriber_list(self, broadcaster_id: str):
        if self._auth_token is None:
            raise RuntimeError('API Manager has not received an auth token')
        prev_cursor = None
        resp = self._api_session.get(
            self.TWITCH_API_URL + 'subscriptions',
            params={'broadcaster_id': broadcaster_id, 'first': 100}
        )
        if not resp.ok:
            raise RuntimeError('Got Error response from twitch: {}'.format(resp.status_code))
        resp = resp.json()
        print('pagination: {}'.format(resp['pagination']))
        if 'cursor' in resp['pagination']:
            pagination_cursor = resp['pagination']['cursor']
        else:
            pagination_cursor = None
        print('data length: {}'.format(len(resp['data'])))
        subscriber_dict = {e['user_id']: e for e in resp['data']}
        while prev_cursor != pagination_cursor:
            resp = self._api_session.get(
                self.TWITCH_API_URL + 'subscriptions',
                params={'broadcaster_id': broadcaster_id, 'after': pagination_cursor, 'first': 100}
            )
            if not resp.ok:
                raise RuntimeError('Got Error response from twitch: {}'.format(resp.status_code))
            resp = resp.json()
            subscriber_dict.update({e['user_id']: e for e in resp['data']})
            print('data length: {}'.format(len(resp['data'])))
            print('pagination: {}'.format(resp['pagination']))
            prev_cursor = pagination_cursor
            if 'cursor' not in resp['pagination']:
                break
            pagination_cursor = resp['pagination']['cursor']
        return list(subscriber_dict.values())

    def is_user_subscribed_by_id(self, broadcaster_id: str, subscriber_id: str) -> bool:
        resp = requests.get(
            self.TWITCH_API_URL + 'subscriptions',
            headers={
                'Client-ID': self._client_id,
                'Authorization': f'Bearer {self._auth_token}'
            },
            params={'broadcaster_id': broadcaster_id, 'user_id': subscriber_id}
        )
        if not resp.ok:
            raise RuntimeError('Got Error response from twitch: {}'.format(resp.status_code))
        user_sub_data = resp.json()['data']
        return len(user_sub_data) > 0


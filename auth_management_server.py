from aiohttp import web


class RequestHandlers:

    def __init__(self, output_queue):
        self._output_queue = output_queue

    @staticmethod
    async def handle_auth_response(_):
        with open('redirect.html', 'rb') as redirect_file:
            redirect_data = redirect_file.read()
        return web.Response(body=redirect_data, content_type='text/html')

    async def handle_auth_redirect(self, request):
        access_token = request.query['access_token']
        self._output_queue.put(access_token)
        return web.Response(text='extracted access_token')


def run_auth_server(app, output_queue):
    handler = RequestHandlers(output_queue)
    app.router.add_get('/', handler.handle_auth_response)
    app.router.add_get('/auth', handler.handle_auth_redirect)
    web.run_app(app, host='127.0.0.1', port=8000)

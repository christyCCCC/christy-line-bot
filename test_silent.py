"""Follow-only welcome behavior and silent-mode regression tests."""
import base64
import hashlib
import hmac
import importlib
import json
import os
import unittest
from unittest.mock import patch, MagicMock

os.environ['LINE_CHANNEL_SECRET'] = 'test-secret-only'
os.environ['LINE_CHANNEL_ACCESS_TOKEN'] = 'test-token-only'
app_module = importlib.import_module('app')


class WelcomeWebhookTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def _signed(self, events):
        body = json.dumps({'events': events}, ensure_ascii=False).encode('utf-8')
        signature = base64.b64encode(hmac.new(b'test-secret-only', body, hashlib.sha256).digest()).decode()
        return self.client.post('/callback', data=body, headers={'X-Line-Signature': signature}, content_type='application/json')

    def test_health_and_status(self):
        self.assertEqual(self.client.get('/health').status_code, 200)
        self.assertEqual(self.client.get('/status').json, {
            'brand': 'Christy P',
            'mode': 'welcome_only',
            'greeting_enabled': True,
            'ordinary_messages_enabled': False,
            'scheduled_broadcast': False,
        })

    def test_invalid_signature(self):
        response = self.client.post('/callback', data=b'{"events":[]}', headers={'X-Line-Signature': 'bad'})
        self.assertEqual(response.status_code, 400)

    def test_text_and_postback_remain_silent(self):
        with patch.object(app_module.urllib.request, 'urlopen') as outbound:
            for event_type in ('message', 'postback'):
                event = {'type': event_type, 'replyToken': 'unused', 'source': {'userId': 'U' + '0' * 32}}
                if event_type == 'message':
                    event['message'] = {'type': 'text', 'text': '探索更多'}
                else:
                    event['postback'] = {'data': 'christy_p:shop'}
                self.assertEqual(self._signed([event]).status_code, 200)
            outbound.assert_not_called()

    def test_empty_verify_event(self):
        with patch.object(app_module.urllib.request, 'urlopen') as outbound:
            self.assertEqual(self._signed([]).status_code, 200)
            outbound.assert_not_called()

    def test_follow_without_token_does_not_send(self):
        with patch.object(app_module.urllib.request, 'urlopen') as outbound:
            self.assertEqual(self._signed([{'type': 'follow'}]).status_code, 200)
            outbound.assert_not_called()

    def test_follow_replies_once_with_exact_approved_message(self):
        response = MagicMock()
        response.status = 200
        connection = MagicMock()
        connection.__enter__.return_value = response
        with patch.object(app_module.urllib.request, 'urlopen', return_value=connection) as outbound:
            self.assertEqual(self._signed([{'type': 'follow', 'replyToken': 'test-reply-token'}]).status_code, 200)
            outbound.assert_called_once()
            request = outbound.call_args.args[0]
            self.assertEqual(request.full_url, 'https://api.line.me/v2/bot/message/reply')
            data = json.loads(request.data)
            self.assertEqual(data, {
                'replyToken': 'test-reply-token',
                'messages': [{'type': 'text', 'text': app_module.WELCOME_MESSAGE}],
            })
            self.assertIn('歡迎來到《萬物可愛論》。', data['messages'][0]['text'])
            self.assertIn("I don't make the world cute. I simply see the cute side of it.", data['messages'][0]['text'])


if __name__ == '__main__':
    unittest.main()

"""Transition smoke tests: no outbound LINE calls can occur in this app."""
import base64
import hashlib
import hmac
import importlib
import json
import os
import sys
import unittest

os.environ['LINE_CHANNEL_SECRET'] = 'test-secret-only'
app_module = importlib.import_module('app')


class SilentWebhookTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def _signed(self, body):
        value = base64.b64encode(hmac.new(b'test-secret-only', body, hashlib.sha256).digest()).decode()
        return self.client.post('/callback', data=body, headers={'X-Line-Signature': value}, content_type='application/json')

    def test_health(self):
        self.assertEqual(self.client.get('/health').status_code, 200)
        self.assertEqual(self.client.get('/status').json, {
            'brand': 'Christy P', 'mode': 'silent', 'scheduled_broadcast': False,
        })

    def test_invalid_signature(self):
        response = self.client.post('/callback', data=b'{}', headers={'X-Line-Signature': 'bad'})
        self.assertEqual(response.status_code, 400)

    def test_text_follow_postback_are_ignored(self):
        for event_type in ('message', 'follow', 'postback'):
            event = {'type': event_type, 'source': {'userId': 'U' + '0' * 32}}
            if event_type == 'message':
                event['message'] = {'type': 'text', 'text': '探索更多'}
            body = json.dumps({'events': [event]}, ensure_ascii=False).encode('utf-8')
            response = self._signed(body)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_data(as_text=True), 'OK')

    def test_empty_verify_event(self):
        self.assertEqual(self._signed(b'{"events":[]}').status_code, 200)


if __name__ == '__main__':
    unittest.main()

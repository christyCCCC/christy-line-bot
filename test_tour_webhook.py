"""Private-tour webhook integration tests with dummy personal data and no deliveries."""
import base64
import hashlib
import hmac
import importlib
import json
import os
import unittest
from unittest.mock import MagicMock, patch

os.environ['LINE_CHANNEL_SECRET'] = 'test-secret-only'
os.environ['LINE_CHANNEL_ACCESS_TOKEN'] = 'test-token-only'
os.environ['AI_CHAT_ENABLED'] = 'false'
app_module = importlib.import_module('app')
tour = importlib.import_module('tour_registration')

SOURCE = {'type': 'user', 'userId': 'Uprivate-tour-dummy'}
COMPLETE = '私人導覽報名\n姓名：測試姓名\n電話：0900000000\n到場日期：11/14\n到場時間：14:00'


class TourWebhookTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        tour.clear_session(app_module.anonymous_session_key(SOURCE))

    @staticmethod
    def connection():
        connection = MagicMock()
        connection.__enter__.return_value.status = 200
        return connection

    def signed(self, text, source=None, reply_token='private-tour-test-token'):
        event = {'type': 'message', 'message': {'type': 'text', 'text': text}, 'source': source or SOURCE}
        if reply_token is not None:
            event['replyToken'] = reply_token
        body = json.dumps({'events': [event]}, ensure_ascii=False).encode()
        sig = base64.b64encode(hmac.new(b'test-secret-only', body, hashlib.sha256).digest()).decode()
        return self.client.post('/callback', data=body, content_type='application/json', headers={'X-Line-Signature': sig})

    def test_trigger_replies_with_exact_four_field_template_once(self):
        with patch.object(app_module.urllib.request, 'urlopen', return_value=self.connection()) as outgoing, patch.object(app_module.chat_engine, 'make_reply') as ai, patch.object(app_module.gallery_cards, 'resolve_text') as gallery:
            self.assertEqual(self.signed('我想報名私人導覽').status_code, 200)
            outgoing.assert_called_once()
            messages = json.loads(outgoing.call_args.args[0].data)['messages']
            self.assertEqual(messages, [{'type': 'text', 'text': tour.FORM_MESSAGE}])
            ai.assert_not_called()
            gallery.assert_not_called()
            self.assertIn('姓名：\n電話：\n到場日期：\n到場時間：', messages[0]['text'])
            self.assertIn('仍需另行確認', messages[0]['text'])

    def test_tour_registration_wins_over_ticket_in_mixed_intent(self):
        with patch.object(app_module.urllib.request, 'urlopen', return_value=self.connection()) as outgoing, patch.object(app_module.ticket_reply, 'resolve_text') as tickets:
            self.assertEqual(self.signed('我想索取門票，還要私人導覽報名').status_code, 200)
            tickets.assert_not_called()
            self.assertEqual(json.loads(outgoing.call_args.args[0].data)['messages'][0]['text'], tour.FORM_MESSAGE)

    def test_completed_fields_acknowledged_without_echo_ai_or_memory(self):
        with patch.object(app_module.urllib.request, 'urlopen', return_value=self.connection()) as outgoing, patch.object(app_module.chat_engine, 'make_reply') as ai, patch.object(app_module.chat_engine, 'remember_gallery_context') as memory, patch.object(app_module.chat_engine, 'remember_ticket_context') as ticket_memory:
            self.assertEqual(self.signed(COMPLETE).status_code, 200)
            outgoing.assert_called_once()
            text = json.loads(outgoing.call_args.args[0].data)['messages'][0]['text']
            self.assertEqual(text, tour.COMPLETE_MESSAGE)
            self.assertNotIn('測試姓名', text)
            self.assertNotIn('0900000000', text)
            self.assertIn('不代表預約已成立', text)
            ai.assert_not_called()
            memory.assert_not_called()
            ticket_memory.assert_not_called()

    def test_partial_labeled_fields_never_reach_ai(self):
        with patch.object(app_module.urllib.request, 'urlopen', return_value=self.connection()) as outgoing, patch.object(app_module.chat_engine, 'make_reply') as ai:
            self.assertEqual(self.signed('姓名：測試姓名\n電話：0900000000').status_code, 200)
            text = json.loads(outgoing.call_args.args[0].data)['messages'][0]['text']
            self.assertIn('到場日期', text)
            self.assertIn('到場時間', text)
            self.assertNotIn('0900000000', text)
            ai.assert_not_called()

    def test_phone_during_registration_uses_template_not_ai(self):
        with patch.object(app_module.urllib.request, 'urlopen', return_value=self.connection()) as outgoing, patch.object(app_module.chat_engine, 'make_reply') as ai:
            self.assertEqual(self.signed('私人導覽報名').status_code, 200)
            self.assertEqual(self.signed('0900000000').status_code, 200)
            last = json.loads(outgoing.call_args.args[0].data)['messages'][0]['text']
            self.assertIn('姓名：', last)
            self.assertNotIn('0900000000', last)
            ai.assert_not_called()

    def test_group_trigger_and_filled_fields_direct_to_private_chat(self):
        for source in ({'type': 'group', 'userId': 'Ud', 'groupId': 'Gdummy'}, {'type': 'room', 'userId': 'Ud', 'roomId': 'Rdummy'}):
            with self.subTest(source_type=source['type']), patch.object(app_module.urllib.request, 'urlopen', return_value=self.connection()) as outgoing, patch.object(app_module.chat_engine, 'make_reply') as ai:
                for text in ('私人導覽報名', COMPLETE):
                    self.assertEqual(self.signed(text, source).status_code, 200)
                    reply = json.loads(outgoing.call_args.args[0].data)['messages'][0]['text']
                    self.assertIn('一對一聊天室', reply)
                    self.assertNotIn('姓名：', reply)
                    self.assertNotIn('0900000000', reply)
                ai.assert_not_called()

    def test_cancel_pending_form_does_not_cancel_real_appointment(self):
        with patch.object(app_module.urllib.request, 'urlopen', return_value=self.connection()) as outgoing:
            self.signed('私人導覽報名')
            self.assertEqual(self.signed('取消報名').status_code, 200)
            reply = json.loads(outgoing.call_args.args[0].data)['messages'][0]['text']
            self.assertIn('停止填寫', reply)
            self.assertNotIn('已取消預約', reply)

    def test_ordinary_chat_keeps_low_question_style_and_no_form(self):
        with patch.object(app_module.urllib.request, 'urlopen', return_value=self.connection()) as outgoing, patch.object(app_module.chat_engine, 'make_reply', return_value=['先歇一下。']) as ai:
            self.assertEqual(self.signed('好累').status_code, 200)
            ai.assert_called_once()
            self.assertEqual(json.loads(outgoing.call_args.args[0].data)['messages'], [{'type': 'text', 'text': '先歇一下。'}])

    def test_missing_reply_token_never_collects_or_sends(self):
        with patch.object(app_module.urllib.request, 'urlopen') as outgoing, patch.object(tour, 'resolve_text') as resolver:
            self.assertEqual(self.signed('私人導覽報名', reply_token=None).status_code, 200)
            resolver.assert_not_called()
            outgoing.assert_not_called()

    def test_text_disabled_never_collects_or_sends(self):
        with patch.object(app_module, 'TEXT_CHAT_ENABLED', False), patch.object(app_module.urllib.request, 'urlopen') as outgoing, patch.object(tour, 'resolve_text') as resolver:
            self.assertEqual(self.signed('私人導覽報名').status_code, 200)
            resolver.assert_not_called()
            outgoing.assert_not_called()

    def test_logs_do_not_contain_registration_personal_fields(self):
        with patch.object(app_module.urllib.request, 'urlopen', return_value=self.connection()), self.assertLogs('app', level='INFO') as logs:
            self.assertEqual(self.signed(COMPLETE).status_code, 200)
        text = '\n'.join(logs.output)
        for value in ('測試姓名', '0900000000', '11/14', '14:00'):
            self.assertNotIn(value, text)

    def test_status_exposes_only_safe_version_and_enabled_flag(self):
        status = self.client.get('/status').json
        self.assertEqual(status['tour_registration_version'], tour.VERSION)
        self.assertTrue(status['tour_registration_enabled'])
        self.assertEqual(status['chat_style'], 'responsive_low_questions_v3')
        self.assertEqual(status['ticket_reply_version'], 'yak_invitation_20261110_user_copy_v2')
        self.assertFalse(status['scheduled_broadcast'])


if __name__ == '__main__':
    unittest.main()

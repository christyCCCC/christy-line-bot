"""Bilingual gallery webhook integration; no real network or LINE delivery."""
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


class GalleryWebhookIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        self.uid = 'U' + '9' * 32

    def signed(self, event):
        body = json.dumps({'events': [event]}, ensure_ascii=False).encode()
        signature = base64.b64encode(hmac.new(b'test-secret-only', body, hashlib.sha256).digest()).decode()
        return self.client.post('/callback', data=body, content_type='application/json', headers={'X-Line-Signature': signature})

    @staticmethod
    def connection():
        connection = MagicMock()
        connection.__enter__.return_value.status = 200
        return connection

    def text_event(self, text):
        return {'type': 'message', 'replyToken': 'test-gallery-token', 'source': {'userId': self.uid}, 'message': {'type': 'text', 'text': text}}

    def test_artist_intent_images_and_full_original_without_ai(self):
        with patch.object(app_module.chat_engine, 'make_reply') as ai, patch.object(app_module.urllib.request, 'urlopen', return_value=self.connection()) as net:
            self.assertEqual(self.signed(self.text_event('想了解藝術家')).status_code, 200)
            ai.assert_not_called()
            net.assert_called_once()
            messages = json.loads(net.call_args.args[0].data)['messages']
            self.assertEqual([m['type'] for m in messages], ['image', 'image', 'text'])
            self.assertEqual(messages[-1]['text'].rstrip('\n'), app_module.ABOUT_ARTIST_MESSAGE)
            self.assertIn('quickReply', messages[-1])

    def test_ten_works_each_has_own_image_bilingual_reading_and_no_ai(self):
        with patch.object(app_module.chat_engine, 'make_reply') as ai, patch.object(app_module.urllib.request, 'urlopen', return_value=self.connection()) as net:
            for index in range(1, 11):
                with self.subTest(index=index):
                    net.reset_mock()
                    self.assertEqual(self.signed(self.text_event(f'作品{index}')).status_code, 200)
                    net.assert_called_once()
                    messages = json.loads(net.call_args.args[0].data)['messages']
                    self.assertEqual(messages[0]['type'], 'image')
                    self.assertTrue(messages[0]['originalContentUrl'].endswith(f'work_{index:02}.jpg'))
                    text = '\n'.join(m['text'] for m in messages if m['type'] == 'text')
                    self.assertRegex(text, '[\u4e00-\u9fff]')
                    self.assertRegex(text, '[A-Za-z]')
                    self.assertIn('quickReply', messages[-1])
                    self.assertTrue(all(len(m['text'].encode('utf-16-le')) // 2 <= 5000 for m in messages if m['type'] == 'text'))
            ai.assert_not_called()

    def test_spoken_chinese_ordinals_open_correct_artwork(self):
        with patch.object(app_module.urllib.request, 'urlopen', return_value=self.connection()) as net:
            for text, index in [('介紹第三件作品', 3), ('第十件', 10)]:
                self.assertEqual(self.signed(self.text_event(text)).status_code, 200)
                image = json.loads(net.call_args.args[0].data)['messages'][0]
                self.assertTrue(image['originalContentUrl'].endswith(f'work_{index:02}.jpg'))

    def test_works_rich_menu_is_enabled_but_pending_menu_is_not(self):
        with patch.object(app_module.urllib.request, 'urlopen', return_value=self.connection()) as net:
            event = {'type': 'postback', 'replyToken': 'menu-test', 'source': {'userId': self.uid}, 'postback': {'data': 'christy_p:artworks'}}
            self.assertEqual(self.signed(event).status_code, 200)
            net.assert_called_once()
            messages = json.loads(net.call_args.args[0].data)['messages']
            self.assertIn('series_intro.jpg', messages[0]['originalContentUrl'])
            self.assertLessEqual(len(messages[-1]['quickReply']['items']), 13)
            for data in ['christy_p:shop', 'christy_p:exhibitions', 'christy_p:stores', 'christy_p:collaboration', 'christy_p:work:999']:
                net.reset_mock()
                event['postback']['data'] = data
                self.assertEqual(self.signed(event).status_code, 200)
                net.assert_not_called()

    def test_daily_topic_after_gallery_goes_back_to_chat(self):
        with patch.object(app_module.urllib.request, 'urlopen', return_value=self.connection()):
            self.assertEqual(self.signed(self.text_event('作品3')).status_code, 200)
            with patch.object(app_module.chat_engine, 'make_reply', return_value=['需要幫你捶捶背嗎？']) as ai:
                self.assertEqual(self.signed(self.text_event('好累')).status_code, 200)
                ai.assert_called_once()

    def test_delivered_gallery_is_available_to_anonymous_chat_memory(self):
        with patch.object(app_module.urllib.request, 'urlopen', return_value=self.connection()):
            self.assertEqual(self.signed(self.text_event('作品6')).status_code, 200)
        key = app_module.anonymous_session_key({'userId': self.uid})
        self.assertEqual(len(key), 64)
        messages = list(app_module.chat_engine._get_session(key).messages)
        self.assertIn('Christy P 圖文介紹', messages[-2]['content'])
        self.assertIn('LOVE BITES', messages[-1]['content'])
        self.assertNotIn(self.uid, str(messages))

    def test_static_images_are_readable_from_deployed_path_locally(self):
        for filename in ['artist_cover.jpg', 'artist_who.jpg', 'artist_age3.jpg', 'artist_age13.jpg', 'artist_age16.jpg', 'series_intro.jpg', 'artist_philosophy.jpg', *[f'work_{i:02}.jpg' for i in range(1, 11)]]:
            with self.subTest(filename=filename):
                response = self.client.get('/static/gallery/' + filename)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, 'image/jpeg')
                self.assertLess(len(response.data), 1024 * 1024)
                response.close()


if __name__ == '__main__':
    unittest.main()

"""Native-welcome and about-artist webhook regression tests."""

import base64
import hashlib
import hmac
import importlib
import json
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ["LINE_CHANNEL_SECRET"] = "test-secret-only"
os.environ["LINE_CHANNEL_ACCESS_TOKEN"] = "test-token-only"
os.environ["AI_CHAT_ENABLED"] = "false"
app_module = importlib.import_module("app")


APPROVED_ABOUT_ARTIST_ORIGINAL = """ABOUT THE ARTIST

關於藝術家

CHRISTY P

Taiwanese Artist & Interdisciplinary Creator

Christy P 是一位以人性觀察為核心的台灣藝術家與跨域創作者，現居高雄。她的創作游移於繪畫、視覺設計與敘事建構之間，關注人們如何隱藏、投射與理解自己的內在情緒。

自幼接受專業美術訓練，繪畫很早便成為她理解自己與世界的語言。青少年時期，「眼睛」與「淚水」開始反覆出現在作品之中，逐漸發展為關於情緒、凝視與自我保護的視覺符號。

此後，她投入視覺設計、品牌策略與創業，在感性直覺與理性結構之間，形成鮮明且具系統性的創作方法。對她而言，設計並非藝術的對立面，而是讓感受得以被準確傳遞的結構。

她的作品融合美式塗鴉語彙、壓克力質地、超現實人物、簡化線條與鮮明互補色。神情平靜的女孩、不對稱的眼睛與黑色陪伴者，共同構成一個看似童真、卻帶有心理張力的世界，映照出人性中相互矛盾、卻同時存在的多重面貌。

作品曾於台灣與韓國展出並獲獎。《萬物可愛論》是她目前的核心創作系列，也是她將多年藝術、設計、品牌與人生觀察重新匯聚後，建立的第一個完整創作體系。

Christy P is a Taiwanese artist and interdisciplinary creator based in Kaohsiung, Taiwan. Her practice moves between painting, visual design, and narrative construction, exploring how people conceal, project, and make sense of their inner emotions.

Formally trained in art from early childhood, she developed painting as a language through which to understand herself and the world. During adolescence, eyes and tears emerged as recurring motifs, gradually becoming visual symbols of emotion, perception, and self-protection.

Her later work across visual design, brand strategy, and entrepreneurship led her to develop a practice that balances artistic intuition with structural clarity. For Christy P, design is not the opposite of art—it is the structure through which feeling can be communicated with precision.

Her work brings together an American graffiti sensibility, acrylic textures, surreal figures, simplified lines, and vivid complementary colors. Composed girls, asymmetric eyes, and black companion creatures form a universe that appears playful yet carries an underlying psychological tension, reflecting the contradictory selves that coexist within us.

Her work has been exhibited and recognized in Taiwan and Korea. EVERYTHING IS CUTE is her current central body of work—the first fully developed creative universe in which her experience across art, design, branding, and human observation converges."""


_ABOUT_PARAGRAPHS = APPROVED_ABOUT_ARTIST_ORIGINAL.split("\n\n")
APPROVED_ABOUT_ARTIST = "\n\n".join(_ABOUT_PARAGRAPHS[1:3] + _ABOUT_PARAGRAPHS[4:9])


class WelcomeAndAboutWebhookTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def _signed_payload(self, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        signature = base64.b64encode(
            hmac.new(b"test-secret-only", body, hashlib.sha256).digest()
        ).decode()
        return self.client.post(
            "/callback",
            data=body,
            headers={"X-Line-Signature": signature},
            content_type="application/json",
        )

    def _signed(self, events):
        return self._signed_payload({"events": events})

    @staticmethod
    def _successful_reply_connection():
        response = MagicMock()
        response.status = 200
        connection = MagicMock()
        connection.__enter__.return_value = response
        return connection

    def test_health_and_default_native_welcome_status(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(
            self.client.get("/status").json,
            {
                "brand": "Christy P",
                "mode": "native_welcome_about_and_chat",
                "greeting_enabled": True,
                "welcome_delivery": "line_official_account",
                "about_artist_enabled": True,
                "ordinary_messages_enabled": True,
                "chat_mode": "rules_only",
                "ai_configured": False,
                "chat_style": "responsive_low_questions_v3",
                "gallery_trigger_version": "natural_requests_v2",
                "welcome_test_command": "測試歡迎",
                "welcome_image_version": "cover_20261108",
                "ticket_reply_version": "yak_invitation_20261110_user_copy_v2",
                "ticket_reply_enabled": True,
                "scheduled_broadcast": False,
                "cards_version": "artist_works_zh_v2",
                "content_language": "zh-TW",
                "artist_cards_count": 7,
                "artwork_cards_count": 10,
            },
        )

    def test_webhook_welcome_fallback_status(self):
        with patch.object(app_module, "WELCOME_DELIVERY", "webhook"):
            self.assertEqual(
                self.client.get("/status").json["mode"],
                "webhook_welcome_about_and_chat",
            )
            self.assertEqual(
                self.client.get("/status").json["welcome_delivery"], "webhook"
            )

    def test_invalid_signature(self):
        response = self.client.post(
            "/callback", data=b'{"events":[]}', headers={"X-Line-Signature": "bad"}
        )
        self.assertEqual(response.status_code, 400)

    def test_default_native_follow_acknowledges_without_outgoing_reply(self):
        follow_event = {"type": "follow", "replyToken": "follow-reply-token"}
        with patch.object(app_module.urllib.request, "urlopen") as outbound:
            self.assertEqual(self._signed([follow_event]).status_code, 200)
            outbound.assert_not_called()

    def test_webhook_fallback_follow_without_reply_token_does_not_send(self):
        with patch.object(app_module, "WELCOME_DELIVERY", "webhook"), patch.object(
            app_module.urllib.request, "urlopen"
        ) as outbound:
            self.assertEqual(self._signed([{"type": "follow"}]).status_code, 200)
            outbound.assert_not_called()

    def test_webhook_fallback_follow_replies_once_with_exact_chinese_welcome(self):
        approved_welcome = Path(app_module.__file__).with_name("welcome_message_zh.txt").read_text(
            encoding="utf-8"
        ).strip()
        self.assertEqual(app_module.WELCOME_MESSAGE, approved_welcome)
        self.assertEqual(len(approved_welcome), 255)
        self.assertNotRegex(approved_welcome.replace("Christy P", ""), r"[A-Za-z]")
        with patch.object(app_module, "WELCOME_DELIVERY", "webhook"), patch.object(
            app_module.urllib.request,
            "urlopen",
            return_value=self._successful_reply_connection(),
        ) as outbound:
            self.assertEqual(
                self._signed([{"type": "follow", "replyToken": "test-reply-token"}]).status_code,
                200,
            )
            outbound.assert_called_once()
            outbound_request = outbound.call_args.args[0]
            self.assertEqual(outbound_request.full_url, "https://api.line.me/v2/bot/message/reply")
            self.assertEqual(
                json.loads(outbound_request.data),
                {
                    "replyToken": "test-reply-token",
                    "messages": [
                        {"type": "image", "originalContentUrl": "https://christy-line-bot.onrender.com/static/gallery/welcome_cover_20261108.jpg", "previewImageUrl": "https://christy-line-bot.onrender.com/static/gallery/welcome_cover_20261108.jpg"},
                        {"type": "text", "text": approved_welcome},
                    ],
                },
            )

    def test_exact_about_postback_replies_once_with_full_approved_biography(self):
        self.assertEqual(app_module.ABOUT_ARTIST_MESSAGE, APPROVED_ABOUT_ARTIST)
        self.assertEqual(
            Path(app_module.__file__).with_name("about_artist_zh.txt").read_text(encoding="utf-8").strip(),
            APPROVED_ABOUT_ARTIST,
        )
        self.assertNotRegex(app_module.ABOUT_ARTIST_MESSAGE.replace("Christy P", "").replace("CHRISTY P", ""), r"[A-Za-z]")
        self.assertNotIn("#", app_module.ABOUT_ARTIST_MESSAGE)
        with patch.object(
            app_module.urllib.request,
            "urlopen",
            return_value=self._successful_reply_connection(),
        ) as outbound:
            event = {
                "type": "postback",
                "replyToken": "about-reply-token",
                "postback": {"data": "christy_p:about"},
            }
            self.assertEqual(self._signed([event]).status_code, 200)
            outbound.assert_called_once()
            payload = json.loads(outbound.call_args.args[0].data)
            self.assertEqual(payload["replyToken"], "about-reply-token")
            self.assertEqual([m["type"] for m in payload["messages"]], ["image", "image", "text"])
            self.assertEqual(payload["messages"][-1]["text"].rstrip("\n"), APPROVED_ABOUT_ARTIST)
            self.assertIn("quickReply", payload["messages"][-1])

    def test_original_bilingual_sources_are_retained_separately_from_display(self):
        root = Path(app_module.__file__).parent
        self.assertEqual(
            (root / "about_artist.txt").read_text(encoding="utf-8").strip(),
            APPROVED_ABOUT_ARTIST_ORIGINAL,
        )
        original_welcome = (root / "welcome_message.txt").read_text(encoding="utf-8").strip()
        chinese_welcome = (root / "welcome_message_zh.txt").read_text(encoding="utf-8").strip()
        self.assertEqual("\n\n".join(original_welcome.split("\n\n")[:7]), chinese_welcome)
        self.assertIn("Welcome to the world of Christy P.", original_welcome)
        self.assertIn("Explore the works, characters, and artist through the menu below.", original_welcome)
        self.assertNotEqual(original_welcome, app_module.WELCOME_MESSAGE)
        self.assertNotEqual(APPROVED_ABOUT_ARTIST_ORIGINAL, app_module.ABOUT_ARTIST_MESSAGE)

    def test_unknown_and_four_pending_menu_postbacks_remain_silent(self):
        other_menu_actions = (
            "christy_p:works",
            "christy_p:shop",
            "christy_p:exhibitions",
            "christy_p:stores",
            "christy_p:stockists",
            "christy_p:collaboration",
        )
        with patch.object(app_module.urllib.request, "urlopen") as outbound:
            for data in (*other_menu_actions, "christy_p:unknown", "unrelated:postback"):
                event = {
                    "type": "postback",
                    "replyToken": "unused-reply-token",
                    "postback": {"data": data},
                }
                self.assertEqual(self._signed([event]).status_code, 200)
            outbound.assert_not_called()

    def test_text_silent_when_disabled_and_stickers_remain_silent(self):
        events = [
            {
                "type": "message",
                "replyToken": "unused-reply-token",
                "message": {"type": "text", "text": "探索更多"},
            },
            {
                "type": "message",
                "replyToken": "unused-reply-token",
                "message": {
                    "type": "sticker",
                    "packageId": "1",
                    "stickerId": "1",
                },
            },
        ]
        with patch.object(app_module, "TEXT_CHAT_ENABLED", False), patch.object(app_module.urllib.request, "urlopen") as outbound:
            self.assertEqual(self._signed(events).status_code, 200)
            outbound.assert_not_called()

    def test_each_typed_text_replies_once_and_hashes_session_identifier(self):
        user_id = "U" + "1" * 32
        with patch.object(app_module.chat_engine, "make_reply", return_value=["測試回覆"] ) as engine, patch.object(
            app_module.urllib.request, "urlopen", return_value=self._successful_reply_connection()
        ) as outbound:
            for text in ("你好", "99", "？", " "):
                event = {"type": "message", "replyToken": "text-test", "source": {"userId": user_id}, "message": {"type": "text", "text": text}}
                outbound.reset_mock()
                self.assertEqual(self._signed([event]).status_code, 200)
                outbound.assert_called_once()
                self.assertEqual(json.loads(outbound.call_args.args[0].data)["messages"], [{"type": "text", "text": "測試回覆"}])
                session_key = engine.call_args.args[1]
                self.assertEqual(len(session_key), 64)
                self.assertNotEqual(session_key, user_id)

    def test_welcome_preview_uses_one_reply_call_with_image_then_exact_chinese(self):
        image_url = "https://christy-line-bot.onrender.com/static/gallery/welcome_cover_20261108.jpg"
        approved = Path(app_module.__file__).with_name("welcome_message_zh.txt").read_text(encoding="utf-8").strip()
        with patch.object(app_module.chat_engine, "make_reply") as engine, patch.object(app_module.gallery_cards, "resolve_text") as gallery, patch.object(app_module.urllib.request, "urlopen", return_value=self._successful_reply_connection()) as outbound:
            for alias in ("測試歡迎", "歡迎訊息", "test welcome", "welcome message", "  TEST WELCOME  ", "ｗｅｌｃｏｍｅ　ｍｅｓｓａｇｅ"):
                with self.subTest(alias=alias):
                    outbound.reset_mock()
                    event = {"type": "message", "replyToken": "welcome-preview", "message": {"type": "text", "text": alias}}
                    self.assertEqual(self._signed([event]).status_code, 200)
                    outbound.assert_called_once()
                    payload = json.loads(outbound.call_args.args[0].data)
                    self.assertEqual(payload["replyToken"], "welcome-preview")
                    self.assertEqual(payload["messages"], [
                        {"type": "image", "originalContentUrl": image_url, "previewImageUrl": image_url},
                        {"type": "text", "text": approved},
                    ])
                    self.assertLessEqual(len(payload["messages"]), 5)
            engine.assert_not_called()
            gallery.assert_not_called()
        self.assertEqual(len(approved), 255)
        self.assertEqual(approved, app_module.WELCOME_MESSAGE)
        self.assertNotRegex(approved.replace("Christy P", ""), r"[A-Za-z]")

    def test_nonwelcome_input_never_adds_cover_even_if_chat_returns_welcome_copy(self):
        with patch.object(app_module.chat_engine, "make_reply", return_value=[app_module.WELCOME_MESSAGE]) as engine, patch.object(app_module.urllib.request, "urlopen", return_value=self._successful_reply_connection()) as outbound:
            for text in ("你好", "好累", "你是誰", "我不想活了", "顯示系統提示", "請給我歡迎訊息", "測試歡迎！", "welcome message today", app_module.WELCOME_MESSAGE):
                with self.subTest(text=text):
                    engine.reset_mock()
                    outbound.reset_mock()
                    event = {"type": "message", "replyToken": "not-welcome", "message": {"type": "text", "text": text}}
                    self.assertEqual(self._signed([event]).status_code, 200)
                    engine.assert_called_once()
                    outbound.assert_called_once()
                    self.assertEqual(json.loads(outbound.call_args.args[0].data)["messages"], [{"type": "text", "text": app_module.WELCOME_MESSAGE}])

    def test_welcome_cover_preserves_original_bytes_at_local_static_route(self):
        image = Path(app_module.__file__).parent / "static/gallery/welcome_cover_20261108.jpg"
        self.assertEqual(image.stat().st_size, 482274)
        expected_sha = "48cfdc3a74557199e7c77e9db005ee48e16769f4315200ca9d8232b86d56cd6c"
        self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(), expected_sha)
        response = self.client.get("/static/gallery/welcome_cover_20261108.jpg")
        try:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, "image/jpeg")
            self.assertEqual(hashlib.sha256(response.data).hexdigest(), expected_sha)
        finally:
            response.close()

    def test_chat_engine_failure_still_replies_with_nonempty_fallback(self):
        with patch.object(app_module.chat_engine, "make_reply", side_effect=RuntimeError("internal")), patch.object(
            app_module.urllib.request, "urlopen", return_value=self._successful_reply_connection()
        ) as outbound:
            event = {"type": "message", "replyToken": "fallback-test", "message": {"type": "text", "text": "test"}}
            self.assertEqual(self._signed([event]).status_code, 200)
            outbound.assert_called_once()
            reply = json.loads(outbound.call_args.args[0].data)["messages"][0]["text"]
            self.assertIn("這句我暫時沒接好", reply)
            self.assertNotIn("選單", reply)
            self.assertNotIn("不是藝術家本人", reply)
            self.assertNotIn("我是 Christy P", reply)

    def test_text_without_token_does_not_invoke_chat_or_reply(self):
        with patch.object(app_module.chat_engine, "make_reply") as engine, patch.object(app_module.urllib.request, "urlopen") as outbound:
            event = {"type": "message", "message": {"type": "text", "text": "no token"}}
            self.assertEqual(self._signed([event]).status_code, 200)
            engine.assert_not_called()
            outbound.assert_not_called()

    def test_nontext_messages_remain_silent_with_chat_enabled(self):
        with patch.object(app_module.urllib.request, "urlopen") as outbound:
            for message_type in ("sticker", "image", "video", "audio", "location", "file"):
                event = {"type": "message", "replyToken": "unused", "message": {"type": message_type}}
                self.assertEqual(self._signed([event]).status_code, 200)
            outbound.assert_not_called()

    def test_empty_verify_event(self):
        with patch.object(app_module.urllib.request, "urlopen") as outbound:
            self.assertEqual(self._signed([]).status_code, 200)
            outbound.assert_not_called()

    def test_about_postback_without_reply_token_does_not_send_or_log_the_token(self):
        event = {
            "type": "postback",
            "postback": {"data": "christy_p:about"},
            "source": {"userId": "U" + "0" * 32},
        }
        with patch.object(app_module.urllib.request, "urlopen") as outbound, self.assertLogs(
            "app", level="INFO"
        ) as captured:
            self.assertEqual(self._signed([event]).status_code, 200)
            outbound.assert_not_called()
        diagnostics = "\n".join(captured.output)
        self.assertIn("event_type=postback", diagnostics)
        self.assertIn("error_status=missing_reply_token", diagnostics)
        self.assertNotIn("userId", diagnostics)
        self.assertNotIn("U" + "0" * 32, diagnostics)

    def test_malformed_payload_is_rejected_and_malformed_events_are_ignored(self):
        with patch.object(app_module.urllib.request, "urlopen") as outbound:
            self.assertEqual(
                self._signed_payload({"events": "not-a-list"}).status_code,
                400,
            )
            self.assertEqual(
                self._signed([None, "not-an-event", {"type": None}]).status_code,
                200,
            )
            outbound.assert_not_called()


if __name__ == "__main__":
    unittest.main()

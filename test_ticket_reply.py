"""Invitation reply regression tests; dummy credentials and mocked LINE calls only.

The uploaded invitation is never decoded or displayed. Its approved SHA256
checks that the local static route serves the original, uncropped bytes.
"""

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
ticket_reply = importlib.import_module("ticket_reply")
app_module = importlib.import_module("app")


EXPECTED_VERSION = "yak_invitation_20261110"
EXPECTED_IMAGE_URL = (
    "https://christy-line-bot.onrender.com/static/gallery/yak_invitation_20261110.jpg"
)
EXPECTED_THANK_YOU = (
    "這張是高雄漾藝術博覽會的邀請函，先收好。\n\n"
    "憑這張邀請函，可以再帶一位朋友一起入場喔。\n"
    "入場時請依邀請函上的說明與現場規定使用。\n\n"
    "謝謝你願意走進我的藝術世界，期待在展場見到你。"
)
EXPECTED_SOURCE_SHA256 = "742796e73665a843834e5e79150986b8d58f5349af5d6bcb762df0493dd8cd89"
EXPECTED_MESSAGES = [
    {
        "type": "image",
        "originalContentUrl": EXPECTED_IMAGE_URL,
        "previewImageUrl": EXPECTED_IMAGE_URL,
    },
    {"type": "text", "text": EXPECTED_THANK_YOU},
]


class TicketResolverTests(unittest.TestCase):
    def assert_invitation(self, text):
        messages = ticket_reply.resolve_text(text)
        self.assertIsInstance(messages, list)
        self.assertEqual(messages, EXPECTED_MESSAGES)

    def test_public_version_image_and_approved_caption(self):
        self.assertEqual(ticket_reply.VERSION, EXPECTED_VERSION)
        self.assertEqual(ticket_reply.IMAGE_URL, EXPECTED_IMAGE_URL)
        self.assertEqual(ticket_reply.THANK_YOU_MESSAGE, EXPECTED_THANK_YOU)

    def test_image_precedes_exact_chinese_extra_guest_and_thanks(self):
        messages = ticket_reply.resolve_text("門票")
        self.assertEqual(messages, EXPECTED_MESSAGES)
        self.assertEqual([message["type"] for message in messages], ["image", "text"])
        self.assertIn("可以再帶一位朋友一起入場", messages[1]["text"])
        self.assertIn("謝謝你", messages[1]["text"])
        self.assertNotRegex(messages[1]["text"], r"[A-Za-z]")
        self.assertLessEqual(len(messages[1]["text"].encode("utf-16-le")) // 2, 5000)

    def test_all_named_traditional_and_simplified_ticket_keywords(self):
        keywords = (
            "門票", "门票", "索票", "贈票", "赠票", "領票", "领票", "取票",
            "票券", "入場券", "入场券", "邀請函", "邀请函", "電子票", "电子票",
            "購票", "购票", "買票", "买票", "售票", "票價", "票价", "免費票", "免费票",
        )
        for keyword in keywords:
            with self.subTest(keyword=keyword):
                self.assert_invitation(keyword)
                self.assert_invitation("請問" + keyword + "的資訊？")

    def test_all_explicit_ticket_request_phrases(self):
        for text in (
            "想要票", "我要票", "給我票", "给我票", "送我票", "一張票", "一张票",
            "兩張票", "两张票",
        ):
            with self.subTest(text=text):
                self.assert_invitation(text)

    def test_natural_questions_are_not_limited_to_three_fixed_commands(self):
        for text in (
            "可以給我高雄漾藝術博覽會的門票嗎？",
            "我想知道怎麼索票", "請問哪裡領票？", "這個展覽票價多少？",
            "電子票要怎麼用？", "想帶朋友去，邀請函可以給我嗎？",
            "想要兩張票一起去看展", "入場要準備什麼？", "怎么入场？",
        ):
            with self.subTest(text=text):
                self.assert_invitation(text)

    def test_related_ticket_text_matches_without_request_or_context(self):
        for text in ("門票資訊", "邀請函已收到", "售票方式", "免費票還有嗎", "入場", "入场"):
            with self.subTest(text=text):
                self.assert_invitation(text)

    def test_negated_ticket_text_still_matches_all_ticket_related_policy(self):
        for text in ("不用門票", "不要門票", "我不需要邀請函", "不用入場券", "不想买票"):
            with self.subTest(text=text):
                self.assert_invitation(text)

    def test_english_ticket_word_boundary_and_case_insensitivity(self):
        for text in ("ticket", "tickets", "TICKET", "TiCkEtS", "Can I get tickets?", "a ticket, please"):
            with self.subTest(text=text):
                self.assert_invitation(text)

    def test_english_nfkc_and_surrounding_whitespace(self):
        for text in ("ＴＩＣＫＥＴ", "ｔｉｃｋｅｔｓ", "  Tickets  ", "\n門票\t", "　邀請函　"):
            with self.subTest(text=text):
                self.assert_invitation(text)

    def test_single_exact_ticket_character(self):
        for text in ("票", "  票  ", "　票　"):
            with self.subTest(text=text):
                self.assert_invitation(text)

    def test_unrelated_chinese_ticket_words_do_not_match(self):
        for text in (
            "股票如何", "發票", "開發票", "投票", "機票", "火車票", "支票", "票選",
            "你好", "好累", "作品",
        ):
            with self.subTest(text=text):
                self.assertIsNone(ticket_reply.resolve_text(text))

    def test_english_substrings_and_empty_text_do_not_match(self):
        for text in ("ticketing software", "ticketed", "myticket", "ticketsystem", "", " ", "　"):
            with self.subTest(text=text):
                self.assertIsNone(ticket_reply.resolve_text(text))


class TicketWebhookTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    @staticmethod
    def connection():
        connection = MagicMock()
        connection.__enter__.return_value.status = 200
        return connection

    def signed(self, events):
        body = json.dumps({"events": events}, ensure_ascii=False).encode("utf-8")
        signature = base64.b64encode(
            hmac.new(b"test-secret-only", body, hashlib.sha256).digest()
        ).decode("ascii")
        return self.client.post(
            "/callback", data=body, content_type="application/json",
            headers={"X-Line-Signature": signature},
        )

    @staticmethod
    def text_event(text):
        return {
            "type": "message",
            "replyToken": "ticket-test-reply",
            "message": {"type": "text", "text": text},
        }

    def test_signed_ticket_request_sends_two_bubbles_in_one_reply_api_call(self):
        with patch.object(app_module.urllib.request, "urlopen", return_value=self.connection()) as outbound:
            self.assertEqual(self.signed([self.text_event("請給我門票")]).status_code, 200)
            outbound.assert_called_once()
            request = outbound.call_args.args[0]
            self.assertEqual(request.full_url, "https://api.line.me/v2/bot/message/reply")
            self.assertEqual(request.get_method(), "POST")
            self.assertEqual(json.loads(request.data), {
                "replyToken": "ticket-test-reply", "messages": EXPECTED_MESSAGES,
            })

    def test_direct_text_route_uses_ticket_without_gallery_or_ai(self):
        with patch.object(app_module.gallery_cards, "resolve_text") as gallery, patch.object(
            app_module.chat_engine, "make_reply"
        ) as chat, patch.object(
            app_module.urllib.request, "urlopen", return_value=self.connection()
        ) as outbound:
            app_module.reply_to_text("ticket-test-reply", "我要票", {})
            gallery.assert_not_called()
            chat.assert_not_called()
            outbound.assert_called_once()
            self.assertEqual(json.loads(outbound.call_args.args[0].data)["messages"], EXPECTED_MESSAGES)

    def test_ticket_keywords_win_before_gallery_and_ai_in_mixed_requests(self):
        with patch.object(app_module.gallery_cards, "resolve_text") as gallery, patch.object(
            app_module.chat_engine, "make_reply"
        ) as chat, patch.object(
            app_module.urllib.request, "urlopen", return_value=self.connection()
        ) as outbound:
            for text in ("想了解藝術家，也想要門票", "作品3和邀請函", "不用門票", "ＴＩＣＫＥＴＳ"):
                with self.subTest(text=text):
                    outbound.reset_mock()
                    self.assertEqual(self.signed([self.text_event(text)]).status_code, 200)
                    outbound.assert_called_once()
                    self.assertEqual(json.loads(outbound.call_args.args[0].data)["messages"], EXPECTED_MESSAGES)
            gallery.assert_not_called()
            chat.assert_not_called()

    def test_ordinary_negative_texts_keep_chat_route_and_do_not_add_invitation(self):
        with patch.object(app_module.gallery_cards, "resolve_text", return_value=None), patch.object(
            app_module.chat_engine, "make_reply", return_value=["一般聊天測試回覆"]
        ) as chat, patch.object(
            app_module.urllib.request, "urlopen", return_value=self.connection()
        ) as outbound:
            for text in (
                "股票如何", "發票", "開發票", "投票", "機票", "火車票", "支票", "票選",
                "你好", "好累", "ticketing software",
            ):
                with self.subTest(text=text):
                    chat.reset_mock()
                    outbound.reset_mock()
                    self.assertEqual(self.signed([self.text_event(text)]).status_code, 200)
                    chat.assert_called_once()
                    outbound.assert_called_once()
                    self.assertEqual(json.loads(outbound.call_args.args[0].data)["messages"], [
                        {"type": "text", "text": "一般聊天測試回覆"},
                    ])

    def test_existing_gallery_text_is_still_routed_without_ai(self):
        gallery_messages = [{"type": "text", "text": "核准畫廊測試回覆"}]
        with patch.object(app_module.gallery_cards, "resolve_text", return_value=gallery_messages) as gallery, patch.object(
            app_module.chat_engine, "make_reply"
        ) as chat, patch.object(app_module.chat_engine, "remember_gallery_context"), patch.object(
            app_module.urllib.request, "urlopen", return_value=self.connection()
        ) as outbound:
            self.assertIsNone(ticket_reply.resolve_text("作品"))
            self.assertEqual(self.signed([self.text_event("作品")]).status_code, 200)
            gallery.assert_called_once()
            chat.assert_not_called()
            outbound.assert_called_once()
            self.assertEqual(json.loads(outbound.call_args.args[0].data)["messages"], gallery_messages)

    def test_exact_welcome_aliases_still_reply_with_welcome_not_invitation(self):
        with patch.object(app_module.gallery_cards, "resolve_text") as gallery, patch.object(
            app_module.chat_engine, "make_reply"
        ) as chat, patch.object(
            app_module.urllib.request, "urlopen", return_value=self.connection()
        ) as outbound:
            for text in ("測試歡迎", "歡迎訊息", "test welcome", "welcome message"):
                with self.subTest(text=text):
                    outbound.reset_mock()
                    self.assertEqual(self.signed([self.text_event(text)]).status_code, 200)
                    outbound.assert_called_once()
                    self.assertEqual(json.loads(outbound.call_args.args[0].data)["messages"], [
                        {"type": "image", "originalContentUrl": app_module.WELCOME_IMAGE_URL,
                         "previewImageUrl": app_module.WELCOME_IMAGE_URL},
                        {"type": "text", "text": app_module.WELCOME_MESSAGE},
                    ])
            gallery.assert_not_called()
            chat.assert_not_called()

    def test_native_follow_remains_silent_not_an_invitation_broadcast(self):
        with patch.object(app_module, "WELCOME_DELIVERY", "line_official_account"), patch.object(
            app_module.urllib.request, "urlopen"
        ) as outbound:
            self.assertEqual(self.signed([{"type": "follow", "replyToken": "unused-test-reply"}]).status_code, 200)
            outbound.assert_not_called()

    def test_ticket_without_reply_token_does_not_resolve_or_send(self):
        event = {"type": "message", "message": {"type": "text", "text": "門票"}}
        with patch.object(ticket_reply, "resolve_text") as resolver, patch.object(
            app_module.chat_engine, "make_reply"
        ) as chat, patch.object(app_module.urllib.request, "urlopen") as outbound:
            self.assertEqual(self.signed([event]).status_code, 200)
            resolver.assert_not_called()
            chat.assert_not_called()
            outbound.assert_not_called()

    def test_disabled_text_chat_does_not_resolve_or_send_ticket(self):
        with patch.object(app_module, "TEXT_CHAT_ENABLED", False), patch.object(
            ticket_reply, "resolve_text"
        ) as resolver, patch.object(app_module.urllib.request, "urlopen") as outbound:
            self.assertEqual(self.signed([self.text_event("門票")]).status_code, 200)
            resolver.assert_not_called()
            outbound.assert_not_called()

    def test_status_reports_enabled_ticket_reply_and_exact_version(self):
        response = self.client.get("/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["ticket_reply_version"], EXPECTED_VERSION)
        self.assertIs(response.json["ticket_reply_enabled"], True)
        self.assertIs(response.json["scheduled_broadcast"], False)

    def test_static_invitation_file_retains_approved_original_bytes(self):
        image = Path(app_module.__file__).parent / "static/gallery/yak_invitation_20261110.jpg"
        self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(), EXPECTED_SOURCE_SHA256)

    def test_static_invitation_route_returns_200_and_original_bytes(self):
        response = self.client.get("/static/gallery/yak_invitation_20261110.jpg")
        try:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, "image/jpeg")
            self.assertEqual(hashlib.sha256(response.data).hexdigest(), EXPECTED_SOURCE_SHA256)
        finally:
            response.close()


if __name__ == "__main__":
    unittest.main()

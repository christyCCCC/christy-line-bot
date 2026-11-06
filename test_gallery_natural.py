"""Natural-language gallery regression tests using approved local source content.

Run: PYTHONDONTWRITEBYTECODE=1 python -m unittest -v test_gallery_natural
No image is opened, no model provider is invoked, and every urlopen is mocked.
"""
import base64
import hashlib
import hmac
import importlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

# These must precede importing app, including when run as a standalone test file.
os.environ["LINE_CHANNEL_SECRET"] = "test-secret-only"
os.environ["LINE_CHANNEL_ACCESS_TOKEN"] = "test-token-only"
os.environ["AI_CHAT_ENABLED"] = "false"
with patch("urllib.request.urlopen", side_effect=AssertionError("Network during import is forbidden")):
    app_module = importlib.import_module("app")


POSITIVE_CASES = (
    ("catalog_works", "作品", "catalog", None),
    ("catalog_paintings", "畫作", "catalog", None),
    ("catalog_portfolio", "作品集", "catalog", None),
    ("introduce_one_trailing_comma", "你幫我介紹一張畫作，", "work", 1),
    ("introduce_one_without_comma", "你幫我介紹一張畫作", "work", 1),
    ("polite_one_artwork", "可以介紹一幅作品嗎", "work", 1),
    ("recommend_one_painting", "隨便推薦一張你的畫", "work", 1),
    ("introduce_third_work", "幫我介紹第三件作品", "work", 3),
    ("introduce_love_bites", "麻煩你介紹愛會咬人", "work", 6),
    ("polite_about_artist", "你可以幫我介紹一下藝術家嗎", "about", None),
)
NEGATIVE_CASES = (
    ("finished_a_painting", "我今天完成一幅畫"),
    ("friends_work", "我朋友的作品很好看"),
    ("reject_introduction", "不要介紹畫作"),
    ("reject_looking", "我不想看你的畫"),
    ("buy_breakfast", "我去買早餐"),
    ("leave_me_alone", "讓我安靜一下"),
    ("tired", "好累"),
    ("introduce_breakfast_shop", "你幫我介紹一家早餐店"),
    ("introduce_credit_card", "你幫我介紹一張信用卡"),
    ("introduce_design_software", "介紹一些設計軟體"),
)


class GalleryNaturalTests(unittest.TestCase):
    SECRET = "test-secret-only"
    ACCESS_TOKEN = "test-token-only"
    REPLY_TOKEN = "test-natural-reply-token"
    REPLY_URL = "https://api.line.me/v2/bot/message/reply"
    IMAGE_BASE = "https://christy-line-bot.onrender.com/static/gallery/"
    CHAT_TEXT = "收到，我陪你聊。"
    TRADITIONAL_CHINESE = r"[畫藝與愛裡讓萬創觀慾會別]"

    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parent
        # Read real approved JSON/text; do not mock gallery content or open images.
        cls.works = {
            int(row["id"]): row
            for row in json.loads((root / "artworks_catalog.json").read_text(encoding="utf-8"))
        }
        cls.artists = {
            row["key"]: row
            for row in json.loads((root / "artist_cards.json").read_text(encoding="utf-8"))
        }
        with (root / "about_artist.txt").open(encoding="utf-8", newline="") as handle:
            cls.about_original = handle.read()

    def setUp(self):
        self._clear_state()
        self.addCleanup(self._clear_state)
        self.enterContext(patch.dict(os.environ, {
            "LINE_CHANNEL_SECRET": self.SECRET,
            "LINE_CHANNEL_ACCESS_TOKEN": self.ACCESS_TOKEN,
            "AI_CHAT_ENABLED": "false",
            "TEXT_CHAT_ENABLED": "true",
        }))
        # Also isolate constants if another unittest imported app earlier.
        self.enterContext(patch.object(app_module, "CHANNEL_SECRET", self.SECRET))
        self.enterContext(patch.object(app_module, "CHANNEL_ACCESS_TOKEN", self.ACCESS_TOKEN))
        self.enterContext(patch.object(app_module, "TEXT_CHAT_ENABLED", True))
        self.chat = self.enterContext(patch.object(
            app_module.chat_engine, "make_reply", return_value=[self.CHAT_TEXT]
        ))
        self.connection = MagicMock(name="mock_reply_connection")
        self.connection.__enter__.return_value.status = 200
        self.connection.__exit__.return_value = False
        # This patches urllib.request globally as app uses the same module object.
        # Any unexpected provider/endpoint call fails rather than accessing network.
        self.network = self.enterContext(patch.object(
            app_module.urllib.request, "urlopen", side_effect=self._mock_reply_only
        ))
        self.client = app_module.app.test_client()

    @staticmethod
    def _clear_state():
        with app_module.gallery_cards._LOCK:
            app_module.gallery_cards._SESSIONS.clear()
        with app_module.chat_engine._MEMORY_LOCK:
            app_module.chat_engine._MEMORY.clear()

    def _mock_reply_only(self, request, *args, **kwargs):
        self.assertEqual(getattr(request, "full_url", None), self.REPLY_URL,
                         "Only the mocked LINE reply endpoint may be called")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"),
                         "Bearer " + self.ACCESS_TOKEN)
        return self.connection

    @staticmethod
    def _uid(text):
        # Intentionally fake UID. app itself computes its anonymous session hash.
        return "test-string-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]

    def _session_key(self, text):
        key = app_module.anonymous_session_key({"userId": self._uid(text)})
        self.assertRegex(key, r"^[0-9a-f]{64}$")
        self.assertNotEqual(key, self._uid(text))
        return key

    def _signed_text(self, text):
        event = {
            "type": "message",
            "replyToken": self.REPLY_TOKEN,
            "source": {"type": "user", "userId": self._uid(text)},
            "message": {"id": "test-natural-message", "type": "text", "text": text},
        }
        body = json.dumps({"events": [event]}, ensure_ascii=False).encode("utf-8")
        signature = base64.b64encode(hmac.new(
            self.SECRET.encode("utf-8"), body, hashlib.sha256
        ).digest()).decode("ascii")
        return self.client.post(
            "/callback", data=body, content_type="application/json",
            headers={"X-Line-Signature": signature},
        )

    def _outbound_messages(self, text):
        response = self._signed_text(text)
        self.assertEqual(response.status_code, 200)
        self.network.assert_called_once()
        request = self.network.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["replyToken"], self.REPLY_TOKEN)
        messages = payload["messages"]
        self.assertGreaterEqual(len(messages), 1)
        self.assertLessEqual(len(messages), 5)
        for message in messages:
            self.assertIn(message["type"], {"image", "text"})
            if message["type"] == "text":
                self.assertLessEqual(len(message["text"].encode("utf-16-le")) // 2, 5000)
        return messages

    def _assert_images(self, messages, expected_filenames):
        images = [message for message in messages if message["type"] == "image"]
        self.assertEqual(len(images), len(expected_filenames))
        for image, filename in zip(images, expected_filenames):
            # Check URL strings only: never fetch or inspect the actual pictures.
            expected_url = self.IMAGE_BASE + filename
            self.assertEqual(image["originalContentUrl"], expected_url)
            self.assertEqual(image["previewImageUrl"], expected_url)

    def _assert_positive(self, text, kind, index):
        messages = self._outbound_messages(text)
        self.chat.assert_not_called()
        self.assertTrue(any(message["type"] == "image" for message in messages))
        texts = [message["text"] for message in messages if message["type"] == "text"]
        self.assertTrue(texts)
        # Concatenation keeps the original verbatim even if LINE text is split.
        full_text = "".join(texts)
        self.assertRegex(full_text, self.TRADITIONAL_CHINESE)
        self.assertRegex(full_text, r"[A-Za-z]{3,}")
        self.assertIn("quickReply", messages[-1])
        if kind == "work":
            row = self.works[index]
            self._assert_images(messages, [row["image_filename"]])
            if index == 1:
                self.assertEqual(row["image_filename"], "work_01.jpg")
            for field in ("title_zh", "title_en", "quote_zh", "quote_en", "reading_zh", "reading_en"):
                self.assertIn(row[field], full_text, field + " must remain verbatim")
            self.assertRegex(full_text, r"(?i)\bquote\b")
            self.assertRegex(full_text, r"(?i)\breading\b")
        elif kind == "catalog":
            row = self.artists["series"]
            self._assert_images(messages, [row["image_filename"]])
            self.assertIn(row["text_zh"], full_text)
            self.assertIn(row["text_en"], full_text)
            self.assertIn(row["title_en"], full_text)
            self.assertRegex(full_text, r"(?i)\b(?:art|artwork|artworks)\s+catalog(?:ue)?\b")
            # The catalogue also contains the series' approved bilingual quote.
            self.assertIn(row["text_zh"].split("\n\n", 1)[0], full_text)
            self.assertIn(row["text_en"].split("\n\n", 1)[0], full_text)
            for work in self.works.values():
                self.assertIn(work["title_zh"], full_text)
                self.assertIn(work["title_en"], full_text)
        else:
            self._assert_images(messages, [
                self.artists["cover"]["image_filename"],
                self.artists["who"]["image_filename"],
            ])
            self.assertEqual(full_text, self.about_original)
            self.assertIn("Christy P", full_text)

    def _assert_negative_resolver(self, text):
        self.assertIsNone(app_module.gallery_cards.resolve_text(text, self._session_key(text)))
        self.network.assert_not_called()
        self.chat.assert_not_called()

    def _assert_negative_webhook(self, text):
        messages = self._outbound_messages(text)
        self.chat.assert_called_once_with(text, self._session_key(text))
        self.assertEqual(messages, [{"type": "text", "text": self.CHAT_TEXT}])
        self.assertFalse(any(message["type"] == "image" for message in messages))


def _positive_test(text, kind, index):
    def test(self):
        self._assert_positive(text, kind, index)
    test.__doc__ = "Gallery image + bilingual approved source, without AI: " + text
    return test


def _negative_test(text, through_webhook):
    def test(self):
        if through_webhook:
            self._assert_negative_webhook(text)
        else:
            self._assert_negative_resolver(text)
    test.__doc__ = ("Normal mocked chat: " if through_webhook else "Resolver must return None: ") + text
    return test


# Separate methods guarantee fresh setUp/cleanup and independent failure reports.
for _name, _text, _kind, _index in POSITIVE_CASES:
    setattr(GalleryNaturalTests, "test_positive_" + _name, _positive_test(_text, _kind, _index))
for _name, _text in NEGATIVE_CASES:
    setattr(GalleryNaturalTests, "test_negative_resolver_" + _name, _negative_test(_text, False))
    setattr(GalleryNaturalTests, "test_negative_webhook_" + _name, _negative_test(_text, True))


if __name__ == "__main__":
    unittest.main()

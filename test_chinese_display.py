"""Traditional-Chinese display contract with retained bilingual local sources.

All checks are local. Images are compared as URL strings, never opened or fetched.
Run: PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v test_chinese_display
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import socket
import unittest
from unittest.mock import patch

import chat_engine
import gallery_cards as gallery


ROOT = Path(__file__).resolve().parent
IMAGE_BASE = "https://christy-line-bot.onrender.com/static/gallery/"
ARTIST_KEYS = ("cover", "who", "age3", "age13", "age16", "series", "philosophy")
ARTIST_IMAGES = {
    "cover": "artist_cover.jpg", "who": "artist_who.jpg", "age3": "artist_age3.jpg",
    "age13": "artist_age13.jpg", "age16": "artist_age16.jpg",
    "series": "series_intro.jpg", "philosophy": "artist_philosophy.jpg",
}
WORK_TITLES = (
    "先別看我", "甜甜的嫉妒", "皇冠可以等", "足夠幸運", "影子一直都在",
    "愛會咬人", "自己戴上皇冠", "怪物也需要愛", "壞主意", "讓我安靜一下",
)
UNAVAILABLE = "第 11／12 件作品圖片尚未提供。"


def display_text(messages):
    return "".join(message["text"] for message in messages if message["type"] == "text")


def work_text(row):
    return (
        f"作品 {row['id']}｜{row['title_zh']}\n\n"
        f"原句\n{row['quote_zh']}\n\n"
        f"作品導讀\n{row['reading_zh']}"
    )


class ChineseDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_bytes = {
            name: (ROOT / name).read_bytes()
            for name in (
                "artist_cards.json", "artworks_catalog.json", "about_artist.txt",
                "welcome_message.txt", "about_artist_zh.txt", "welcome_message_zh.txt",
            )
        }
        cls.artists = {
            row["key"]: row for row in json.loads(cls.source_bytes["artist_cards.json"].decode("utf-8"))
        }
        cls.works = {
            int(row["id"]): row for row in json.loads(cls.source_bytes["artworks_catalog.json"].decode("utf-8"))
        }
        cls.about = cls.source_bytes["about_artist_zh.txt"].decode("utf-8")
        cls.welcome = cls.source_bytes["welcome_message_zh.txt"].decode("utf-8").strip()

    def setUp(self):
        self._clear_state()
        self.addCleanup(self._clear_state)
        self.enterContext(patch.dict(os.environ, {"AI_CHAT_ENABLED": "false", "AI_DISABLED": "false"}))
        self.network = self.enterContext(patch.object(
            chat_engine.urllib.request, "urlopen", side_effect=AssertionError("Network forbidden")
        ))
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")))
        self.enterContext(patch.object(socket, "create_connection", side_effect=AssertionError("Network forbidden")))

    @staticmethod
    def _clear_state():
        with gallery._LOCK:
            gallery._SESSIONS.clear()
        with chat_engine._MEMORY_LOCK:
            chat_engine._MEMORY.clear()

    def assert_chinese_only(self, text):
        self.assertRegex(text, r"[\u4e00-\u9fff]")
        # The brand and platform/technology proper names are the sole exceptions.
        without_names = re.sub(r"(?i)\bChristy\s+P\b|\b(?:LINE|AI)\b", "", text)
        self.assertNotRegex(without_names, r"[A-Za-z]", "English display text is forbidden")
        for heading in ("ABOUT THE ARTIST", "Artwork catalogue", "Artwork", "Quote", "Reading"):
            self.assertNotRegex(text, r"(?i)\b" + re.escape(heading) + r"\b")

    def assert_display(self, messages, filenames):
        self.assertIsNotNone(messages)
        self.assertLessEqual(len(messages), 5)
        images = [message for message in messages if message["type"] == "image"]
        self.assertEqual(len(images), len(filenames))
        for message, filename in zip(images, filenames):
            self.assertEqual(message["originalContentUrl"], IMAGE_BASE + filename)
            self.assertEqual(message["previewImageUrl"], IMAGE_BASE + filename)
        full_text = display_text(messages)
        self.assert_chinese_only(full_text)
        for message in messages:
            if message["type"] == "text":
                self.assertGreater(gallery._utf16_len(message["text"]), 0)
                self.assertLessEqual(gallery._utf16_len(message["text"]), 5000)
            for item in message.get("quickReply", {}).get("items", []):
                self.assert_chinese_only(item["action"]["label"])
        self.network.assert_not_called()
        return full_text

    def test_all_seven_artist_nodes_have_exact_chinese_text_and_unchanged_image_urls(self):
        self.assertEqual(set(self.artists), set(ARTIST_KEYS))
        for key in ARTIST_KEYS:
            with self.subTest(key=key):
                row = self.artists[key]
                self.assertEqual(row["image_filename"], ARTIST_IMAGES[key])
                messages = gallery.resolve_postback("christy_p:artist:" + key, "all-artists")
                text = self.assert_display(messages, [ARTIST_IMAGES[key]])
                self.assertEqual(text, self.about if key == "who" else row["text_zh"])
                self.assertNotIn(row["text_en"], text)
                self.assertNotIn(row["title_en"], text)
                if key != "who":
                    self.assertIn(row["text_zh"].split("\n\n", 1)[0], text)

    def test_about_routes_preserve_entire_chinese_biography_not_json_summary(self):
        for route in ("關於藝術家", "1", "WHO IS CHRISTY P?", "tell me about christy p"):
            with self.subTest(route=route):
                messages = gallery.resolve_text(route, "full-about")
                self.assertEqual(self.assert_display(messages, ["artist_cover.jpg", "artist_who.jpg"]), self.about)
                self.assertNotIn(self.artists["who"]["text_zh"], display_text(messages))
        self.assertEqual(chat_engine.ABOUT_FILE, ROOT / "about_artist_zh.txt")
        self.assertEqual(chat_engine.approved_about_artist(), self.about.strip())
        self.assert_chinese_only(chat_engine.approved_about_artist())

    def test_catalog_is_exact_chinese_series_plus_ten_chinese_titles_and_notice(self):
        self.assertEqual(set(self.works), set(range(1, 11)))
        self.assertEqual(tuple(self.works[index]["title_zh"] for index in range(1, 11)), WORK_TITLES)
        directory = "作品目錄\n\n" + "\n".join(
            f"{index}. {self.works[index]['title_zh']}" for index in range(1, 11)
        ) + "\n\n" + UNAVAILABLE
        for route in ("作品", "Show me artworks", "EVERYTHING IS CUTE"):
            with self.subTest(route=route):
                messages = gallery.resolve_text(route, "chinese-catalog")
                text = self.assert_display(messages, ["series_intro.jpg"])
                self.assertEqual(text, self.artists["series"]["text_zh"] + "\n\n" + directory)
                self.assertNotIn(self.artists["series"]["text_en"], text)
                self.assertNotIn(self.artists["series"]["title_en"], text)
                for row in self.works.values():
                    self.assertNotIn(row["title_en"], text)
                actions = [item["action"]["data"] for item in messages[-1]["quickReply"]["items"]]
                self.assertEqual(actions, [f"christy_p:work:{index}" for index in range(1, 11)] + ["christy_p:about"])

    def test_all_ten_works_keep_exact_chinese_original_quotes_and_readings(self):
        for index in range(1, 11):
            with self.subTest(index=index):
                row = self.works[index]
                filename = f"work_{index:02d}.jpg"
                self.assertEqual(row["image_filename"], filename)
                messages = gallery.resolve_postback(f"christy_p:work:{index}", "all-works")
                text = self.assert_display(messages, [filename])
                self.assertEqual(text, work_text(row))
                for field in ("title_zh", "quote_zh", "reading_zh"):
                    self.assertIn(row[field], text, field + " must stay verbatim")
                for field in ("title_en", "quote_en", "reading_en"):
                    self.assertNotIn(row[field], text)
                actions = [item["action"]["data"] for item in messages[-1]["quickReply"]["items"]]
                self.assertEqual(f"christy_p:work:{index - 1}" in actions, index > 1)
                self.assertEqual(f"christy_p:work:{index + 1}" in actions, index < 10)
                self.assertIn("christy_p:about", actions)
                self.assertIn("christy_p:artworks", actions)

    def test_original_english_titles_still_resolve_but_display_only_chinese(self):
        for index, row in sorted(self.works.items()):
            with self.subTest(index=index):
                messages = gallery.resolve_text("introduce " + row["title_en"], "english-title-route")
                self.assertEqual(self.assert_display(messages, [row["image_filename"]]), work_text(row))

    def test_artist_forward_back_navigation_and_both_endings_are_only_chinese(self):
        gallery.resolve_postback("christy_p:artist:cover", "artist-nav")
        for key in ARTIST_KEYS[1:]:
            messages = gallery.resolve_text("下一張", "artist-nav")
            self.assertEqual(self.assert_display(messages, [ARTIST_IMAGES[key]]), self.about if key == "who" else self.artists[key]["text_zh"])
        ending = gallery.resolve_text("next", "artist-nav")
        self.assert_display(ending, [])
        self.assertIn("藝術家故事", display_text(ending))
        self.assertIsNone(gallery.resolve_text("next", "artist-nav"))
        gallery.resolve_postback("christy_p:artist:age3", "artist-back")
        previous = gallery.resolve_text("上一張", "artist-back")
        self.assertEqual(self.assert_display(previous, ["artist_who.jpg"]), self.about)
        self.assert_display(gallery.resolve_text("previous", "artist-back"), [])

    def test_work_forward_back_navigation_and_both_endings_are_only_chinese(self):
        gallery.resolve_postback("christy_p:artworks", "work-nav")
        for index in range(1, 11):
            messages = gallery.resolve_text("下一件", "work-nav")
            self.assertEqual(self.assert_display(messages, [f"work_{index:02d}.jpg"]), work_text(self.works[index]))
        ending = gallery.resolve_text("next", "work-nav")
        text = self.assert_display(ending, [])
        self.assertIn("10 件作品", text)
        self.assertIn(UNAVAILABLE, text)
        self.assertIsNone(gallery.resolve_text("next", "work-nav"))
        gallery.resolve_postback("christy_p:work:2", "work-back")
        previous = gallery.resolve_text("上一件", "work-back")
        self.assertEqual(self.assert_display(previous, ["work_01.jpg"]), work_text(self.works[1]))
        self.assert_display(gallery.resolve_text("previous", "work-back"), [])

    def test_welcome_preview_is_one_exact_255_character_chinese_message(self):
        self.assertEqual(chat_engine.WELCOME_FILE, ROOT / "welcome_message_zh.txt")
        self.assertEqual(len(self.welcome), 255)
        self.assertEqual(chat_engine.approved_welcome_preview(), [self.welcome])
        for route in ("測試歡迎", "歡迎訊息", "test welcome", "welcome message"):
            with self.subTest(route=route):
                self.assertEqual(chat_engine.make_reply(route, "chinese-welcome"), [self.welcome])
        self.assert_chinese_only(self.welcome)
        self.network.assert_not_called()

    def test_chat_series_and_all_twelve_approved_title_names_are_chinese_only(self):
        for route in ("2", "作品系列", "EVERYTHING IS CUTE"):
            with self.subTest(route=route):
                replies = chat_engine.make_reply(route, "chinese-series")
                self.assertEqual(len(replies), 1)
                self.assert_chinese_only(replies[0])
                self.assertIn("萬物可愛論", replies[0])
                self.assertIn("不是替傷害開脫", replies[0])
        for route in ("有哪些作品名稱？", "What are the work titles?"):
            with self.subTest(route=route):
                replies = chat_engine.make_reply(route, "chinese-title-list")
                self.assertEqual(len(replies), 1)
                self.assert_chinese_only(replies[0])
                self.assertIn("12 件作品", replies[0])
                for index, title in enumerate(WORK_TITLES + ("我們都是", "萬物可愛論"), 1):
                    self.assertIn(f"{index} {title}\n", replies[0])
                self.assertIn("尺寸與價格尚不能自行補充", replies[0])
        self.network.assert_not_called()

    def test_all_display_operations_leave_original_bilingual_sources_untouched(self):
        for key in ARTIST_KEYS:
            gallery.resolve_postback("christy_p:artist:" + key, "retain-sources")
        gallery.resolve_postback("christy_p:about", "retain-sources")
        gallery.resolve_postback("christy_p:artworks", "retain-sources")
        for index in range(1, 11):
            gallery.resolve_postback(f"christy_p:work:{index}", "retain-sources")
        chat_engine.approved_about_artist()
        chat_engine.approved_welcome_preview()
        for name, original in self.source_bytes.items():
            with self.subTest(source=name):
                self.assertEqual((ROOT / name).read_bytes(), original)
        for row in self.artists.values():
            for field in ("title_en", "text_en"):
                self.assertRegex(row[field], r"[A-Za-z]")
        for row in self.works.values():
            for field in ("title_en", "quote_en", "reading_en"):
                self.assertRegex(row[field], r"[A-Za-z]")
        self.assertIn(b"ABOUT THE ARTIST", self.source_bytes["about_artist.txt"])
        self.assertIn(b"Christy P is a Taiwanese artist", self.source_bytes["about_artist.txt"])
        self.assertIn(b"Welcome to the world of Christy P.", self.source_bytes["welcome_message.txt"])
        self.assertIn(b"Explore the works, characters, and artist through the menu below.", self.source_bytes["welcome_message.txt"])


if __name__ == "__main__":
    unittest.main()

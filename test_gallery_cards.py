"""Isolated tests; no real JSON, network, secrets, images, or app imports needed.

Run only this module: PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v test_gallery_cards
"""
from __future__ import annotations

import concurrent.futures
import copy
import io
import json
import socket
import unittest
from unittest.mock import patch

import gallery_cards as gallery


ABOUT_ORIGINAL = (
    "ABOUT THE ARTIST\n\n關於藝術家\n\nCHRISTY P\n\n"
    "這是完整核准原文的固定測試種子，不可用 JSON 短版取代。\n\n"
    "This fixed seed stands for the entire approved bilingual original.\n"
)
ABOUT = (
    "關於藝術家\n\nChristy P\n\n"
    "這是完整核准中文原文的固定測試種子，不可用圖卡短版取代。\n\n"
    "完整段落與換行都必須保留，不能混入英文介紹。\n"
)
ARTISTS = [
    {
        "key": key, "title_zh": "藝術家節點 " + str(index),
        "title_en": "Artist card " + key, "image_filename": "artist_" + key + ".jpg",
        "text_zh": "核准詳細中文：" + str(index), "text_en": "Approved detailed English: " + key,
    }
    for index, key in enumerate(gallery._ARTIST_KEYS, 1)
]
WORKS = [
    {
        "id": index, "title_zh": "測試作品" + str(index), "title_en": "Seed Artwork " + str(index),
        "image_filename": f"work_{index:02d}.png", "quote_zh": f"原句中文 {index}",
        "quote_en": f"Original quote {index}", "reading_zh": f"完整中文導讀 {index}",
        "reading_en": f"Complete English reading {index}",
    }
    for index in range(1, 11)
]
WORKS[2].update(title_zh="讓我安靜一下", title_en="Leave Me Alone")
WORKS[3].update(title_zh="先別看我", title_en="Don't Look at Me Yet")
WORKS[4].update(title_zh="怪物", title_en="Monster")
WORKS[5].update(title_zh="我好嫉妒", title_en="I Am Jealous")
WORKS[6].update(title_zh="好累", title_en="So Tired")
WORKS[7].update(title_zh="別人的展覽", title_en="Someone Else's Exhibition")


def joined_text(messages):
    return "".join(message["text"] for message in messages if message["type"] == "text")


def action_data(messages):
    return [item["action"]["data"] for item in messages[-1].get("quickReply", {}).get("items", [])]


class GalleryTests(unittest.TestCase):
    def setUp(self):
        self.artists = copy.deepcopy(ARTISTS)
        self.works = copy.deepcopy(WORKS)
        self.about = ABOUT
        self.clock = 10000.0
        self.patches = [
            patch.object(gallery, "_read_json", side_effect=self.mock_json),
            patch.object(gallery, "_read_about", side_effect=lambda: self.about),
            patch.object(gallery, "_now", side_effect=lambda: self.clock),
            patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")),
            patch.object(socket, "create_connection", side_effect=AssertionError("Network forbidden")),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        with gallery._LOCK:
            gallery._SESSIONS.clear()
        self.addCleanup(gallery._SESSIONS.clear)

    def mock_json(self, path):
        if path.name == "artist_cards.json":
            return copy.deepcopy(self.artists)
        if path.name == "artworks_catalog.json":
            return copy.deepcopy(self.works)
        raise AssertionError("Unexpected file: " + str(path))

    def assert_native_limits(self, messages):
        self.assertIsNotNone(messages)
        self.assertLessEqual(len(messages), 5)
        for message in messages:
            self.assertIn(message["type"], {"image", "text"})
            if message["type"] == "image":
                self.assertEqual(message["originalContentUrl"], message["previewImageUrl"])
                self.assertTrue(message["originalContentUrl"].startswith(gallery._IMAGE_BASE))
            else:
                self.assertGreater(gallery._utf16_len(message["text"]), 0)
                self.assertLessEqual(gallery._utf16_len(message["text"]), 5000)
            items = message.get("quickReply", {}).get("items", [])
            self.assertLessEqual(len(items), 13)
            for item in items:
                self.assertEqual(item["type"], "action")
                action = item["action"]
                self.assertEqual(action["type"], "postback")
                self.assertNotIn("displayText", action)
                self.assertLessEqual(gallery._utf16_len(action["label"]), 20)
                self.assertTrue(action["data"].startswith("christy_p:"))

    def test_status_only_fixed_contract(self):
        self.assertEqual(gallery.content_status(), {
            "cards_version": "artist_works_zh_v2", "content_language": "zh-TW",
            "artist_cards_count": 7, "artwork_cards_count": 10,
        })

    def test_natural_about_entries_preserve_entire_original(self):
        for text in [
            "1", "１", "關於藝術家", "艺术家介绍", "想了解藝術家", "想認識藝術家",
            "我想了解Christy P", "Christy P是誰", "WHO IS CHRISTY P?", "請介紹藝術家",
            "想了解一下藝術家", "可以介紹藝術家嗎", "tell me about christy p", "關於 CHRISTY P",
            "請問 Christy P 是誰", "我想知道Christy P是誰", "可以請介紹一下藝術家嗎", "我想了解藝術家的故事",
        ]:
            with self.subTest(text=text):
                result = gallery.resolve_text(text, "about-session")
                self.assert_native_limits(result)
                self.assertEqual([item["type"] for item in result], ["image", "image", "text"])
                self.assertTrue(result[0]["originalContentUrl"].endswith("artist_cover.jpg"))
                self.assertTrue(result[1]["originalContentUrl"].endswith("artist_who.jpg"))
                self.assertEqual(joined_text(result), self.about)
                self.assertIn("christy_p:artist:age3", action_data(result))
                self.assertNotIn(self.artists[1]["text_zh"], joined_text(result))

    def test_who_postback_uses_original_not_short_json(self):
        result = gallery.resolve_postback("christy_p:artist:who", "who")
        self.assertEqual(len(result), 2)
        self.assertEqual(joined_text(result), self.about)
        self.assert_native_limits(result)

    def test_every_artist_image_and_detailed_chinese_text(self):
        for row in self.artists:
            with self.subTest(key=row["key"]):
                result = gallery.resolve_postback("christy_p:artist:" + row["key"], "artist")
                self.assert_native_limits(result)
                self.assertEqual(result[0]["originalContentUrl"], gallery._IMAGE_BASE + row["image_filename"])
                self.assertEqual(joined_text(result), self.about if row["key"] == "who" else row["text_zh"])
                self.assertNotIn(row["text_en"], joined_text(result))
                self.assertNotIn(row["title_en"], joined_text(result))
                self.assertNotRegex(joined_text(result).replace("Christy P", ""), r"[A-Za-z]")

    def test_series_natural_entries_and_complete_directory(self):
        for text in ["2", "２", "作品系列", "作品介紹", "作品目录", "想看作品", "介绍万物可爱论", "Show me artworks", "EVERYTHING IS CUTE", "介紹《萬物可愛論》", "想看 Christy P 的作品"]:
            with self.subTest(text=text):
                result = gallery.resolve_text(text, "catalog")
                self.assert_native_limits(result)
                self.assertEqual(len(result), 2)
                self.assertTrue(result[0]["originalContentUrl"].endswith("artist_series.jpg"))
                detail = joined_text(result)
                series = next(row for row in self.artists if row["key"] == "series")
                self.assertIn(series["text_zh"], detail)
                self.assertNotIn(series["text_en"], detail)
                self.assertNotIn(series["title_en"], detail)
                self.assertIn("作品目錄", detail)
                for row in self.works:
                    self.assertIn(row["title_zh"], detail)
                    self.assertNotIn(row["title_en"], detail)
                self.assertIn(gallery._UNAVAILABLE, detail)
                self.assertNotRegex(detail, r"[A-Za-z]")
                self.assertEqual(len(action_data(result)), 11)
                self.assertEqual(action_data(result)[:10], [f"christy_p:work:{index}" for index in range(1, 11)])

    def test_series_separate_directory_when_needed(self):
        next(row for row in self.artists if row["key"] == "series")["text_zh"] = "中" * 4900
        result = gallery.resolve_postback("christy_p:artworks", "long-series")
        self.assert_native_limits(result)
        self.assertEqual(len(result), 3)
        self.assertNotIn("quickReply", result[1])
        self.assertEqual(len(action_data(result)), 11)
        self.assertIn(gallery._UNAVAILABLE, result[2]["text"])

    def test_series_rejects_impossible_length_without_truncating(self):
        next(row for row in self.artists if row["key"] == "series")["text_zh"] = "😀" * 3000
        self.assertIsNone(gallery.resolve_postback("christy_p:artworks", "impossible-series"))
        self.assertNotIn("impossible-series", gallery._SESSIONS)

    def test_all_ten_work_images_quotes_readings_and_button_endpoints(self):
        for row in self.works:
            index = row["id"]
            with self.subTest(index=index):
                result = gallery.resolve_postback(f"christy_p:work:{index}", "works")
                self.assertEqual(len(result), 2)
                self.assert_native_limits(result)
                self.assertEqual(result[0]["originalContentUrl"], gallery._IMAGE_BASE + row["image_filename"])
                for field in ["title_zh", "quote_zh", "reading_zh"]:
                    self.assertIn(row[field], joined_text(result))
                for field in ["title_en", "quote_en", "reading_en"]:
                    self.assertNotIn(row[field], joined_text(result))
                self.assertEqual(joined_text(result), (
                    f"作品 {index}｜{row['title_zh']}\n\n"
                    f"原句\n{row['quote_zh']}\n\n"
                    f"作品導讀\n{row['reading_zh']}"
                ))
                self.assertNotRegex(joined_text(result), r"[A-Za-z]")
                actions = action_data(result)
                self.assertIn("christy_p:artworks", actions)
                self.assertIn("christy_p:about", actions)
                self.assertEqual(f"christy_p:work:{index - 1}" in actions, index > 1)
                self.assertEqual(f"christy_p:work:{index + 1}" in actions, index < 10)
                self.assertNotIn("christy_p:work:11", actions)

    def test_unicode_numbers_and_zero_padding(self):
        for text in ["第1件", "第01件", "作品1", "作品01", "WORK 01", "第０１件", "作品１", "ＷＯＲＫ ０１", "第¹件", "想看作品０１", "介紹第01件"]:
            with self.subTest(text=text):
                result = gallery.resolve_text(text, "numbers")
                self.assertIsNotNone(result)
                self.assertTrue(result[0]["originalContentUrl"].endswith("work_01.png"))
        for text in ["作品0", "第11件", "第12件", "work 999", "作品-1"]:
            with self.subTest(text=text):
                self.assertIsNone(gallery.resolve_text(text, "numbers"))

    def test_named_work_triggers(self):
        for text, index in [("Seed Artwork 1", 1), ("SEED ARTWORK 2", 2), ("測試作品1", 1), ("介紹測試作品1", 1), ("想看測試作品2", 2), ("作品 測試作品2", 2), ("show me Seed Artwork 2", 2)]:
            with self.subTest(text=text):
                result = gallery.resolve_text(text, "titles")
                self.assertTrue(result[0]["originalContentUrl"].endswith(f"work_{index:02d}.png"))

    def test_ambiguous_titles_require_request_or_work_mode(self):
        for text, index in [("讓我安靜一下", 3), ("leave me alone", 3), ("先別看我", 4), ("怪物", 5), ("我好嫉妒", 6), ("好累", 7), ("別人的展覽", 8)]:
            with self.subTest(text=text):
                self.assertIsNone(gallery.resolve_text(text, "ordinary"))
                gallery.resolve_postback("christy_p:about", "artist-not-work")
                self.assertIsNone(gallery.resolve_text(text, "artist-not-work"))
                result = gallery.resolve_text("介紹" + text, "explicit")
                self.assertTrue(result[0]["originalContentUrl"].endswith(f"work_{index:02d}.png"))
                gallery.resolve_postback("christy_p:artworks", "in-work")
                result = gallery.resolve_text(text, "in-work")
                if index in (3, 4):
                    self.assertTrue(result[0]["originalContentUrl"].endswith(f"work_{index:02d}.png"))
                else:
                    self.assertIsNone(result)
                    self.assertIsNone(gallery.resolve_text("next", "in-work"))
        self.assertIsNotNone(gallery.resolve_text("作品讓我安靜一下", "explicit-work"))
        self.assertIsNotNone(gallery.resolve_text("introduce Leave Me Alone", "explicit-en"))
        self.assertIsNone(gallery.resolve_text("我想安靜", "ordinary"))

    def test_daily_age_emotion_and_negated_question_do_not_trigger(self):
        for text in ["好累", "我十三歲", "我13歲", "我16歲", "我１６岁", "我在畫畫", "我好嫉妒", "怪物", "我想安靜", "別人的展覽", "不了解藝術家嗎", "今天想買早餐", "我今年十六歲", "藝術家今天也好累", "我三歲時開始畫畫"]:
            with self.subTest(text=text):
                self.assertIsNone(gallery.resolve_text(text, "daily"))
                gallery.resolve_postback("christy_p:about", "daily-artist")
                self.assertIsNone(gallery.resolve_text(text, "daily-artist"))
                self.assertIsNone(gallery.resolve_text("next", "daily-artist"))
                gallery.resolve_postback("christy_p:artworks", "daily-work")
                self.assertIsNone(gallery.resolve_text(text, "daily-work"))
                self.assertIsNone(gallery.resolve_text("next", "daily-work"))

    def test_artist_short_questions_require_context_or_artist_reference(self):
        for short, key in [("三歲怎麼開始畫畫", "age3"), ("眼睛與淚水", "age13"), ("十六歲如何養活自己", "age16"), ("創作理念", "philosophy")]:
            with self.subTest(short=short):
                self.assertIsNone(gallery.resolve_text(short, "no-context"))
                result = gallery.resolve_text("Christy P " + short, "explicit-artist")
                self.assertTrue(result[0]["originalContentUrl"].endswith("artist_" + key + ".jpg"))
                result = gallery.resolve_text("藝術家" + short, "explicit-artist-zh")
                self.assertTrue(result[0]["originalContentUrl"].endswith("artist_" + key + ".jpg"))
                gallery.resolve_postback("christy_p:about", "artist-context")
                result = gallery.resolve_text(short, "artist-context")
                self.assertTrue(result[0]["originalContentUrl"].endswith("artist_" + key + ".jpg"))
                gallery.resolve_postback("christy_p:artworks", "work-context")
                self.assertIsNone(gallery.resolve_text(short, "work-context"))
        self.assertTrue(gallery.resolve_text("妳的創作起點", "pointed")[0]["originalContentUrl"].endswith("artist_age3.jpg"))
        self.assertTrue(gallery.resolve_text("妳的創作起點是什麼", "pointed")[0]["originalContentUrl"].endswith("artist_age3.jpg"))

    def test_artist_next_sequence_cover_and_previous(self):
        gallery.resolve_postback("christy_p:artist:cover", "story")
        for key in gallery._ARTIST_ORDER:
            result = gallery.resolve_text("下一張", "story")
            self.assertTrue(result[0]["originalContentUrl"].endswith("artist_" + key + ".jpg"))
            self.assert_native_limits(result)
        self.assertNotIn("christy_p:artist:who", action_data(result))
        result = gallery.resolve_text("next", "story")
        self.assertEqual(result[0]["type"], "text")
        self.assertIsNone(gallery.resolve_text("next", "story"))
        gallery.resolve_postback("christy_p:about", "story2")
        result = gallery.resolve_text("繼續", "story2")
        self.assertTrue(result[0]["originalContentUrl"].endswith("artist_age3.jpg"))
        result = gallery.resolve_text("上一張", "story2")
        self.assertTrue(result[0]["originalContentUrl"].endswith("artist_who.jpg"))

    def test_work_next_previous_and_end_at_ten(self):
        gallery.resolve_postback("christy_p:artworks", "walk")
        for index in range(1, 11):
            result = gallery.resolve_text("下一件", "walk")
            self.assertTrue(result[0]["originalContentUrl"].endswith(f"work_{index:02d}.png"))
        result = gallery.resolve_text("next", "walk")
        self.assert_native_limits(result)
        self.assertEqual(result[0]["type"], "text")
        self.assertIn("10", joined_text(result))
        self.assertIn(gallery._UNAVAILABLE, joined_text(result))
        self.assertIsNone(gallery.resolve_text("next", "walk"))
        gallery.resolve_postback("christy_p:work:2", "back")
        self.assertTrue(gallery.resolve_text("上一件", "back")[0]["originalContentUrl"].endswith("work_01.png"))

    def test_next_commands_are_inert_without_gallery(self):
        for text in ["下一件", "下一張", "繼續", "上一件", "下一個", "next", "NEXT", "previous"]:
            with self.subTest(text=text):
                self.assertIsNone(gallery.resolve_text(text, "never-opened"))
        gallery.resolve_postback("christy_p:work:1")
        self.assertIsNone(gallery.resolve_text("next"))
        self.assertNotIn("", gallery._SESSIONS)

    def test_clear_negation_and_topic_shift_clear_only_gallery(self):
        for text in ["不要介紹藝術家", "不想看作品", "不用了", "停止介紹", "不看了", "回到聊天", "清除對話", "不要认识艺术家", "不用介紹了", "don't introduce the artist", "stop showing artworks", "好累", "好累我想睡", "怪物", "我好嫉妒", "別人的展覽", "買早餐", "我十三歲", "不了解藝術家嗎"]:
            with self.subTest(text=text):
                gallery.resolve_postback("christy_p:work:1", "shift")
                self.assertIsNone(gallery.resolve_text(text, "shift"))
                self.assertNotIn("shift", gallery._SESSIONS)
                self.assertIsNone(gallery.resolve_text("next", "shift"))
        gallery.resolve_postback("christy_p:work:1", "unaffected")
        gallery.resolve_postback("christy_p:work:2", "stopped")
        gallery.resolve_text("不用了", "stopped")
        self.assertIsNotNone(gallery.resolve_text("next", "unaffected"))

    def test_sessions_isolated_and_do_not_store_chat_content(self):
        gallery.resolve_postback("christy_p:work:1", "hashed-A")
        gallery.resolve_postback("christy_p:artist:age13", "hashed-B")
        result_a = gallery.resolve_text("next", "hashed-A")
        result_b = gallery.resolve_text("next", "hashed-B")
        self.assertTrue(result_a[0]["originalContentUrl"].endswith("work_02.png"))
        self.assertTrue(result_b[0]["originalContentUrl"].endswith("artist_age16.jpg"))
        self.assertEqual(set(gallery._SESSIONS["hashed-A"]), {"kind", "index", "last_seen"})
        self.assertEqual(set(gallery._SESSIONS["hashed-B"]), {"kind", "key", "last_seen"})
        self.assertEqual(gallery._SESSIONS["hashed-A"]["index"], 2)

    def test_ttl_expires_exactly_at_30_minutes_and_refreshes_on_gallery(self):
        gallery.resolve_postback("christy_p:work:1", "expires")
        self.clock += 1799
        self.assertIsNotNone(gallery.resolve_text("next", "expires"))
        self.clock += 1799
        self.assertIsNotNone(gallery.resolve_text("next", "expires"))
        self.clock += 1800
        self.assertIsNone(gallery.resolve_text("next", "expires"))
        self.assertNotIn("expires", gallery._SESSIONS)

    def test_memory_capped_at_500_and_least_recently_used(self):
        for index in range(500):
            gallery.resolve_postback("christy_p:work:1", f"hashed-{index}")
        gallery.resolve_text("next", "hashed-0")
        gallery.resolve_postback("christy_p:work:1", "hashed-500")
        self.assertEqual(len(gallery._SESSIONS), 500)
        self.assertIn("hashed-0", gallery._SESSIONS)
        self.assertNotIn("hashed-1", gallery._SESSIONS)
        self.assertIsNone(gallery.resolve_text("next", "hashed-1"))
        self.clock += 1800
        gallery.resolve_text("next", "hashed-0")
        self.assertEqual(len(gallery._SESSIONS), 0)

    def test_thread_safe_navigation(self):
        gallery.resolve_postback("christy_p:work:1", "same-key")
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _: gallery.resolve_text("next", "same-key"), range(9)))
        images = sorted(int(result[0]["originalContentUrl"].split("work_")[1].split(".")[0]) for result in results)
        self.assertEqual(images, list(range(2, 11)))
        self.assertEqual(gallery._SESSIONS["same-key"]["index"], 10)

    def test_unknown_postback_and_malicious_payloads_never_reply(self):
        for data in ["christy_p:work:11", "christy_p:work:0", "christy_p:work:01", "christy_p:artist:unknown", "christy_p:artist:../../secret", "christy_p:work:https://evil.test/x.png", "christy_p:work:1?x=y", "christy_p:about\n", "CHRISTY_P:ABOUT", "other:about", "", None]:
            with self.subTest(data=data):
                gallery.resolve_postback("christy_p:work:1", "unsafe")
                self.assertIsNone(gallery.resolve_postback(data, "unsafe"))
                self.assertIsNone(gallery.resolve_text("next", "unsafe"))
        self.assertIsNone(gallery.resolve_text("作品https://evil.test/1.jpg", "unsafe"))

    def test_validated_json_ids_and_filename_path_safety(self):
        self.artists += [dict(self.artists[0], key="untrusted", image_filename="other.jpg")]
        self.works[0]["image_filename"] = "../secret.png"
        self.works[1]["image_filename"] = "https://evil.test/x.png"
        self.works[2]["image_filename"] = "/etc/passwd.jpg"
        self.works += [dict(self.works[3], id=11), dict(self.works[3], id=True), dict(self.works[3], id="evil")]
        self.assertEqual(gallery.content_status()["artwork_cards_count"], 7)
        self.assertEqual(gallery.content_status()["artist_cards_count"], 7)
        for index in [1, 2, 3, 11]:
            self.assertIsNone(gallery.resolve_postback(f"christy_p:work:{index}", "bad-json"))
        self.assertIsNotNone(gallery.resolve_postback("christy_p:work:4", "good-json"))
        self.works[3]["id"] = "04"
        self.assertIsNotNone(gallery.resolve_postback("christy_p:work:4", "string-id"))

    def test_huge_user_numbers_are_controlled_without_conversion_errors(self):
        self.assertIsNone(gallery.resolve_text("作品" + "9" * 10000, "huge"))
        result = gallery.resolve_text("作品" + "0" * 10000 + "1", "zero-padded")
        self.assertTrue(result[0]["originalContentUrl"].endswith("work_01.png"))
        self.works += [dict(self.works[0], id="9" * 10000)]
        self.assertEqual(gallery.content_status()["artwork_cards_count"], 10)

    def test_missing_or_empty_data_is_controlled_and_can_recover(self):
        self.artists, self.works, self.about = [], [], ""
        self.assertEqual(gallery.content_status(), {
            "cards_version": "artist_works_zh_v2", "content_language": "zh-TW",
            "artist_cards_count": 0, "artwork_cards_count": 0,
        })
        self.assertIsNone(gallery.resolve_text("藝術家介紹", "missing"))
        self.assertIsNone(gallery.resolve_postback("christy_p:artworks", "missing"))
        self.assertIsNone(gallery.resolve_postback("christy_p:work:1", "missing"))
        self.artists, self.works, self.about = copy.deepcopy(ARTISTS), copy.deepcopy(WORKS), ABOUT
        self.assertIsNotNone(gallery.resolve_text("藝術家介紹", "missing"))

    def test_missing_about_does_not_substitute_short_json(self):
        self.about = ""
        self.assertIsNone(gallery.resolve_postback("christy_p:about", "missing-about"))
        self.assertIsNone(gallery.resolve_postback("christy_p:artist:who", "missing-about"))
        self.assertIsNotNone(gallery.resolve_postback("christy_p:artist:age3", "other-artist"))

    def test_actual_reader_errors_are_nonfatal(self):
        # Undo only reader mocks here; filesystem itself remains mocked.
        with patch.object(gallery, "_read_json", GalleryTests.original_read_json):
            for error in [FileNotFoundError(), PermissionError(), UnicodeError()]:
                with self.subTest(error=type(error).__name__), patch.object(gallery.Path, "read_text", side_effect=error):
                    self.assertEqual(gallery._read_json(gallery._DATA_DIR / "artist_cards.json"), [])
            for value in ["broken JSON", "{}", "null"]:
                with patch.object(gallery.Path, "read_text", return_value=value):
                    self.assertEqual(gallery._read_json(gallery._DATA_DIR / "artist_cards.json"), [])
            with patch.object(gallery.Path, "read_text", return_value=json.dumps(ARTISTS)):
                self.assertEqual(len(gallery._read_json(gallery._DATA_DIR / "artist_cards.json")), 7)
        with patch.object(gallery, "_read_about", GalleryTests.original_read_about):
            with patch.object(gallery.Path, "open", side_effect=FileNotFoundError()):
                self.assertEqual(gallery._read_about(), "")
            with patch.object(gallery.Path, "open", autospec=True, return_value=io.StringIO(ABOUT + "\r\n")) as opened:
                self.assertEqual(gallery._read_about(), ABOUT + "\r\n")
                opened.assert_called_once_with(
                    gallery._DATA_DIR / "about_artist_zh.txt", encoding="utf-8", newline="",
                )

    def test_utf16_emoji_splitting_preserves_original_and_message_cap(self):
        self.assertEqual(gallery._utf16_len("中😀"), 3)
        self.about = "😀" * 3000 + "\n\n核准中文結尾\n"
        result = gallery.resolve_postback("christy_p:about", "utf16")
        self.assert_native_limits(result)
        self.assertEqual(len(result), 4)
        self.assertEqual(joined_text(result), self.about)
        self.assertEqual(gallery._utf16_len(result[2]["text"]), 5000)
        self.about = "😀" * 8000  # Four text messages + two images would exceed five.
        self.assertIsNone(gallery.resolve_postback("christy_p:about", "too-large"))
        self.assertNotIn("too-large", gallery._SESSIONS)
        self.assertEqual(len(gallery._split_text("😀" * 2500)), 1)
        with self.assertRaises(ValueError):
            gallery._button("😀" * 11, "christy_p:about")

    def test_chinese_about_header_paragraphs_survive_split_boundary(self):
        header = "關於藝術家\n\nChristy P\n\n"
        self.about = header + "中" * (5000 - gallery._utf16_len(header) - 1) + "\n\n下一段完整中文。\n"
        result = gallery.resolve_postback("christy_p:about", "chinese-boundary")
        self.assert_native_limits(result)
        self.assertEqual(len(result), 4)
        self.assertEqual(gallery._utf16_len(result[2]["text"]), 5000)
        self.assertTrue(result[2]["text"].startswith(header))
        self.assertTrue(result[2]["text"].endswith("\n"))
        self.assertTrue(result[3]["text"].startswith("\n下一段完整中文。"))
        self.assertEqual(joined_text(result), self.about)
        self.assertNotRegex(joined_text(result).replace("Christy P", ""), r"[A-Za-z]")

    def test_display_does_not_overwrite_original_bilingual_source_fixtures(self):
        artists_before, works_before = copy.deepcopy(self.artists), copy.deepcopy(self.works)
        original_before = ABOUT_ORIGINAL
        for row in self.artists:
            gallery.resolve_postback("christy_p:artist:" + row["key"], "retained-artist")
        gallery.resolve_postback("christy_p:artworks", "retained-catalog")
        for row in self.works:
            gallery.resolve_postback(f"christy_p:work:{row['id']}", "retained-work")
        self.assertEqual(self.artists, artists_before)
        self.assertEqual(self.works, works_before)
        self.assertEqual(ABOUT_ORIGINAL, original_before)
        self.assertIn("ABOUT THE ARTIST", ABOUT_ORIGINAL)
        self.assertIn("approved bilingual original", ABOUT_ORIGINAL)
        self.assertNotIn("ABOUT THE ARTIST", self.about)
        for row in self.artists:
            self.assertTrue(row["title_en"])
            self.assertTrue(row["text_en"])
        for row in self.works:
            for field in ("title_en", "quote_en", "reading_en"):
                self.assertTrue(row[field])

    def test_large_titles_do_not_overflow_quick_reply_labels(self):
        for row in self.works:
            row["title_zh"] = "非常長的作品標題😀" * 4 + str(row["id"])
            row["title_en"] = "A very long English work title " * 4 + str(row["id"])
        result = gallery.resolve_postback("christy_p:artworks", "large-labels")
        self.assert_native_limits(result)
        self.assertEqual(len(action_data(result)), 11)


# Capture real functions before per-test mocks, without reading any files.
GalleryTests.original_read_json = staticmethod(gallery._read_json)
GalleryTests.original_read_about = staticmethod(gallery._read_about)

if __name__ == "__main__":
    unittest.main()

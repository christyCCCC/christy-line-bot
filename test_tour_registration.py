"""Tour resolver unit tests only: no app import, credentials, network, or AI calls."""

import hashlib
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import tour_registration as tour


EXPECTED_FORM = (
    "私人導覽報名\n\n請填寫以下資料，完成後直接回傳在這個聊天室：\n\n"
    "姓名：\n電話：\n到場日期：\n到場時間：\n\n"
    "資料僅供導覽報名與聯繫使用；導覽是否成立及時間安排，仍需另行確認。"
)
EXPECTED_COMPLETE = (
    "已收到你在聊天室填寫的報名資料，謝謝你。\n"
    "導覽安排仍需確認，這則回覆不代表預約已成立。"
)
EXPECTED_CANCEL = (
    "好的，這裡先停止填寫資料；若先前已有確認的安排，取消事宜仍需另行確認。"
)
EXPECTED_GROUP = (
    "私人導覽報名需要姓名與電話，請到官方帳號的一對一聊天室輸入「私人導覽報名」，"
    "避免在群組公開個人資料。"
)
COMPLETE_PAYLOAD = (
    "姓名：測試用姓名\n電話：0912345678\n到場日期：2026/11/13\n到場時間：15:00"
)


def text_reply(message):
    return [{"type": "text", "text": message}]


class TourRegistrationTests(unittest.TestCase):
    def setUp(self):
        with tour._state_lock:
            tour._active_sessions.clear()

    def tearDown(self):
        with tour._state_lock:
            tour._active_sessions.clear()

    def assert_form(self, text, session_key=""):
        self.assertEqual(tour.resolve_text(text, session_key), text_reply(EXPECTED_FORM))

    def test_version_and_exact_approved_messages(self):
        self.assertEqual(tour.VERSION, "private_tour_registration_20261110")
        self.assertEqual(tour.FORM_MESSAGE, EXPECTED_FORM)
        self.assertEqual(tour.COMPLETE_MESSAGE, EXPECTED_COMPLETE)
        self.assertEqual(tour.CANCEL_MESSAGE, EXPECTED_CANCEL)
        self.assertEqual(tour.GROUP_MESSAGE, EXPECTED_GROUP)

    def test_all_explicit_traditional_and_simplified_triggers(self):
        for keyword in (
            "私人導覽", "私人导览", "導覽報名", "导览报名", "預約導覽", "预约导览",
            "報名導覽", "报名导览", "專人導覽報名", "专人导览报名",
        ):
            with self.subTest(keyword=keyword):
                self.assert_form(keyword)
                self.assert_form("我想" + keyword + "，謝謝")

    def test_english_triggers_word_boundaries_and_case(self):
        for text in (
            "private tour", "Can I have a PRIVATE TOUR?", "guided tour registration",
            "Guided Tour Registration please", "guided\ttour\nregistration",
        ):
            with self.subTest(text=text):
                self.assert_form(text)
        for text in ("privately touring", "private tournament", "guided tour", "registration"):
            with self.subTest(non_trigger=text):
                self.assertIsNone(tour.resolve_text(text))

    def test_nfkc_and_chinese_keyword_whitespace(self):
        for text in ("ＰＲＩＶＡＴＥ　ＴＯＵＲ", "　私人導覽報名　", "私人 導覽 報名"):
            with self.subTest(text=text):
                self.assert_form(text)

    def test_mixed_ticket_intent_returns_only_tour_form(self):
        self.assert_form("索取門票也要私人導覽報名")
        self.assert_form("I'd like tickets and a private tour")

    def test_generic_words_and_everyday_topics_do_not_collect(self):
        for text in ("報名", "报名", "導覽", "导览", "好累", "早餐", "作品", "你好", "藝術家會到場嗎"):
            with self.subTest(text=text):
                self.assertIsNone(tour.resolve_text(text))

    def test_simple_chinese_and_english_negations_are_respected(self):
        for text in (
            "不要私人導覽", "不想報名導覽", "我不需要私人導覽", "不用導覽報名",
            "不想预约导览", "私人導覽不用了", "不要私人導覽，門票就好",
            "I don't want a private tour", "no private tour", "not interested in guided tour registration",
        ):
            with self.subTest(text=text):
                self.assertIsNone(tour.resolve_text(text, "negative-session"))
                self.assertEqual(len(tour._active_sessions), 0)

    def test_complete_traditional_data_acknowledged_without_echo(self):
        messages = tour.resolve_text(COMPLETE_PAYLOAD)
        self.assertEqual(messages, text_reply(EXPECTED_COMPLETE))
        for pii in ("測試用姓名", "0912345678", "2026/11/13", "15:00"):
            self.assertNotIn(pii, repr(messages))

    def test_simplified_nfkc_colons_and_fullwidth_values(self):
        payload = (
            "姓名﹕测试姓名\n电话：０９１２３４５６７８\n"
            "到场日期：２０２６／１１／１３\n到场时间：１５：００"
        )
        self.assertEqual(tour.resolve_text(payload), text_reply(EXPECTED_COMPLETE))

    def test_labeled_payload_precedes_matching_title_and_field_values(self):
        for payload in (
            "私人導覽報名\n\n" + COMPLETE_PAYLOAD,
            COMPLETE_PAYLOAD.replace("測試用姓名", "不要先生"),
            COMPLETE_PAYLOAD.replace("測試用姓名", "取消導覽報名先生"),
        ):
            with self.subTest(payload=payload):
                self.assertEqual(tour.resolve_text(payload), text_reply(EXPECTED_COMPLETE))

    def test_partial_data_lists_only_missing_field_names_in_order(self):
        payload = "私人導覽報名\n姓名：測試用姓名\n電話：0912345678"
        expected = "還需要補上：到場日期、到場時間。請將四項資料填在同一則訊息再回傳，導覽安排仍需另行確認。"
        self.assertEqual(tour.resolve_text(payload, "partial"), text_reply(expected))
        self.assertNotIn("0912345678", repr(tour._active_sessions))

    def test_blank_field_values_count_as_missing(self):
        payload = "姓名：測試用姓名\n電話：　\n到場日期：2026/11/13\n到場時間：\t"
        expected = "還需要補上：電話、到場時間。請將四項資料填在同一則訊息再回傳，導覽安排仍需另行確認。"
        self.assertEqual(tour.resolve_text(payload), text_reply(expected))

    def test_all_empty_copied_template_returns_form_not_four_missing_warnings(self):
        for payload in (
            "私人導覽報名\n\n姓名：\n電話：\n到場日期：\n到場時間：",
            "姓名：\n电话：\n到场日期：\n到场时间：",
            EXPECTED_FORM,
            "姓名：",
        ):
            with self.subTest(payload=payload):
                self.assert_form(payload)

    def test_crlf_cr_and_indented_label_lines(self):
        payload = "  姓名 ： 測試用姓名\r\n\t電話: 0912345678\r到場日期 : 2026/11/13\n  到場時間: 15:00"
        self.assertEqual(tour.resolve_text(payload), text_reply(EXPECTED_COMPLETE))

    def test_nonempty_values_are_not_invented_validated_or_confirmed(self):
        payload = "姓名：不要先生\n電話：稍後提供\n到場日期：待確認\n到場時間：待確認"
        self.assertEqual(tour.resolve_text(payload), text_reply(EXPECTED_COMPLETE))
        self.assertNotIn("已預約成功", EXPECTED_COMPLETE)
        self.assertNotIn("資料庫", EXPECTED_COMPLETE)

    def test_duplicate_empty_label_does_not_use_earlier_value(self):
        payload = COMPLETE_PAYLOAD + "\n電話："
        expected = "還需要補上：電話。請將四項資料填在同一則訊息再回傳，導覽安排仍需另行確認。"
        self.assertEqual(tour.resolve_text(payload), text_reply(expected))

    def test_malformed_and_empty_inputs_fail_safely(self):
        for text in (None, 42, [], {}, b"private tour", "", "\n\t　", "姓名", "姓名=匿名", "不知道：內容"):
            with self.subTest(text=text):
                self.assertIsNone(tour.resolve_text(text))

    def test_group_triggers_and_payloads_never_show_collecting_form_or_pii(self):
        for payload in (
            "私人導覽報名", "private tour", "索取門票也要私人導覽報名",
            COMPLETE_PAYLOAD, "姓名：測試用姓名", "姓名：\n電話：",
            "不要私人導覽", "取消導覽報名",
        ):
            with self.subTest(payload=payload):
                reply = tour.resolve_text(payload, "group", private_chat=False)
                self.assertEqual(reply, text_reply(EXPECTED_GROUP))
                self.assertNotIn("0912345678", repr(reply))
                self.assertNotIn("測試用姓名", repr(reply))
                self.assertNotIn("到場日期：", repr(reply))
                self.assertEqual(len(tour._active_sessions), 0)

    def test_group_unrelated_text_is_unhandled(self):
        for text in ("早餐", "作品", "報名", "導覽", "0912345678"):
            with self.subTest(text=text):
                self.assertIsNone(tour.resolve_text(text, "group", private_chat=False))

    def test_active_phone_guard_never_repeats_number(self):
        self.assert_form("私人導覽報名", "active")
        for phone in ("0912345678", "０９１２３４５６７８", "+886 912-345-678", "我的電話是0912345678"):
            with self.subTest(phone=phone):
                reply = tour.resolve_text(phone, "active")
                self.assertEqual(reply, text_reply(tour.CONTACT_GUARD_MESSAGE))
                self.assertNotIn("0912345678", repr(reply))

    def test_obvious_unlabeled_personal_data_guard_is_active_only(self):
        self.assert_form("私人導覽", "active")
        for text in (
            "我叫測試用姓名", "我的名字是測試用姓名", "林小明", "陳美玲", "王小明",
            "2026/11/13", "15:00", "11/14 14:00", "11月14日下午2點", "下午2點半",
            "林小明\n0912345678\n11/14\n14:00",
        ):
            with self.subTest(text=text):
                self.assertEqual(tour.resolve_text(text, "active"), text_reply(tour.CONTACT_GUARD_MESSAGE))
                self.assertIsNone(tour.resolve_text(text, "not-active"))

    def test_no_key_no_global_phone_guard_and_no_cross_session_guard(self):
        self.assert_form("私人導覽", "")
        self.assertEqual(len(tour._active_sessions), 0)
        self.assertIsNone(tour.resolve_text("0912345678"))
        self.assert_form("私人導覽", "one")
        self.assertIsNone(tour.resolve_text("0912345678", "two"))
        for key in (None, 1, [], {}):
            with self.subTest(session_key=key):
                self.assert_form("私人導覽", key)
                self.assertIsNone(tour.resolve_text("0912345678", key))
        self.assertEqual(len(tour._active_sessions), 1)

    def test_active_normal_topics_not_swallowed_and_guard_remains_until_ttl(self):
        self.assert_form("私人導覽", "active")
        for text in ("好累", "早餐", "作品", "謝謝", "谢谢", "何時", "何时", "我喜歡第15號作品", "15"):
            with self.subTest(text=text):
                self.assertIsNone(tour.resolve_text(text, "active"))
        self.assertEqual(tour.resolve_text("0912345678", "active"), text_reply(tour.CONTACT_GUARD_MESSAGE))

    def test_complete_clears_flag_and_state_contains_only_digest_timestamp(self):
        raw_key = "anonymous-session-example"
        self.assert_form("私人導覽", raw_key)
        expected_digest = hashlib.sha256(raw_key.encode()).hexdigest()
        self.assertEqual(list(tour._active_sessions), [expected_digest])
        self.assertTrue(all(isinstance(value, (float, int)) for value in tour._active_sessions.values()))
        tour.resolve_text("姓名：測試用姓名\n電話：0912345678", raw_key)
        state = repr(tour._active_sessions)
        for forbidden in (raw_key, "測試用姓名", "0912345678", "姓名", "電話"):
            self.assertNotIn(forbidden, state)
        self.assertEqual(tour.resolve_text(COMPLETE_PAYLOAD, raw_key), text_reply(EXPECTED_COMPLETE))
        self.assertEqual(len(tour._active_sessions), 0)
        self.assertIsNone(tour.resolve_text("0912345678", raw_key))

    def test_ttl_expires_at_thirty_minutes_and_does_not_refresh_on_phone(self):
        with patch.object(tour.time, "monotonic", return_value=100.0):
            self.assert_form("私人導覽", "ttl")
        with patch.object(tour.time, "monotonic", return_value=1899.0):
            self.assertEqual(tour.resolve_text("0912345678", "ttl"), text_reply(tour.CONTACT_GUARD_MESSAGE))
        with patch.object(tour.time, "monotonic", return_value=1900.0):
            self.assertIsNone(tour.resolve_text("0912345678", "ttl"))
            self.assertEqual(len(tour._active_sessions), 0)

    def test_bounded_two_hundred_flags_with_concurrent_calls(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            replies = list(pool.map(lambda index: tour.resolve_text("私人導覽", f"session-{index}"), range(240)))
        self.assertTrue(all(reply == text_reply(EXPECTED_FORM) for reply in replies))
        self.assertEqual(len(tour._active_sessions), 200)
        self.assertTrue(all(len(key) == 64 for key in tour._active_sessions))

    def test_cancel_stops_local_flag_never_claims_appointment_cancelled(self):
        for text in (
            "取消導覽報名", "取消私人導覽", "取消导览报名", "cancel private tour",
            "取消報名", "算了", "不用", "不要",
        ):
            with self.subTest(text=text):
                self.assert_form("私人導覽", "cancel")
                self.assertEqual(tour.resolve_text(text, "cancel"), text_reply(EXPECTED_CANCEL))
                self.assertEqual(len(tour._active_sessions), 0)
                self.assertIsNone(tour.resolve_text("0912345678", "cancel"))
        self.assertNotIn("取消成功", EXPECTED_CANCEL)
        self.assertIsNone(tour.resolve_text("算了", "inactive"))
        self.assertEqual(tour.resolve_text("取消導覽報名"), text_reply(EXPECTED_CANCEL))

    def test_public_clear_and_clear_command_return_none_for_engine_confirmation(self):
        self.assert_form("私人導覽", "clear-one")
        self.assert_form("私人導覽", "keep-two")
        tour.clear_session("clear-one")
        self.assertIsNone(tour.resolve_text("0912345678", "clear-one"))
        self.assertEqual(tour.resolve_text("0912345678", "keep-two"), text_reply(tour.CONTACT_GUARD_MESSAGE))
        for command in ("清除對話", "清除对话"):
            with self.subTest(command=command):
                self.assert_form("私人導覽", "clear")
                self.assertIsNone(tour.resolve_text(command, "clear"))
                self.assertIsNone(tour.resolve_text("0912345678", "clear"))
        tour.clear_session(None)
        tour.clear_session("does-not-exist")

    def test_all_handled_responses_are_text_only_and_have_no_extra_fields(self):
        for payload in ("私人導覽報名", COMPLETE_PAYLOAD, "姓名：測試用姓名", "取消導覽報名"):
            with self.subTest(payload=payload):
                reply = tour.resolve_text(payload)
                self.assertTrue(reply)
                for message in reply:
                    self.assertEqual(set(message), {"type", "text"})
                    self.assertEqual(message["type"], "text")
                    self.assertLessEqual(len(message["text"].encode("utf-16-le")) // 2, 5000)


if __name__ == "__main__":
    unittest.main()

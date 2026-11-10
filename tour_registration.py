"""Private-tour text routing; no AI, persistence, notifications, or PII logging.

Submitted details remain in the LINE Official Account chat for its administrators
 to review manually. This module acknowledges receipt, never an appointment.
The only retained state is a hashed session key and a monotonic timestamp. Normal
conversation remains routable while that short-lived contact-data guard is active.
"""

import hashlib
import re
import threading
import time
import unicodedata
from collections import OrderedDict

VERSION = "private_tour_registration_20261110"
FORM_MESSAGE = (
    "私人導覽報名\n\n"
    "請填寫以下資料，完成後直接回傳在這個聊天室：\n\n"
    "姓名：\n電話：\n到場日期：\n到場時間：\n\n"
    "資料僅供導覽報名與聯繫使用；導覽是否成立及時間安排，仍需另行確認。"
)
COMPLETE_MESSAGE = (
    "已收到你在聊天室填寫的報名資料，謝謝你。\n"
    "導覽安排仍需確認，這則回覆不代表預約已成立。"
)
CANCEL_MESSAGE = (
    "好的，這裡先停止填寫資料；若先前已有確認的安排，取消事宜仍需另行確認。"
)
GROUP_MESSAGE = (
    "私人導覽報名需要姓名與電話，請到官方帳號的一對一聊天室輸入「私人導覽報名」，"
    "避免在群組公開個人資料。"
)
CONTACT_GUARD_MESSAGE = "請將四項資料依格式填在同一則訊息後回傳。\n\n" + FORM_MESSAGE

_FIELDS = ("姓名", "電話", "到場日期", "到場時間")
_FIELD_ALIASES = {
    "姓名": "姓名", "電話": "電話", "电话": "電話",
    "到場日期": "到場日期", "到场日期": "到場日期",
    "到場時間": "到場時間", "到场时间": "到場時間",
}
# A label must start a line. Only presence/nonemptiness, never values, is returned.
_FIELD_LINE = re.compile(
    r"^[^\S\n]*(姓名|電話|电话|到場日期|到场日期|到場時間|到场时间)"
    r"[^\S\n]*:[^\S\n]*([^\n]*)$", re.MULTILINE
)
_KEYWORDS = (
    "私人導覽", "私人导览", "導覽報名", "导览报名", "預約導覽", "预约导览",
    "報名導覽", "报名导览", "專人導覽報名", "专人导览报名",
)
_CHINESE_TRIGGER = "(?:" + "|".join(map(re.escape, _KEYWORDS)) + ")"
_ENGLISH_TRIGGER = re.compile(
    r"\b(?:private[\s-]+tour|guided[\s-]+tour[\s-]+registration)\b", re.I
)
_NEGATED_CHINESE = re.compile(
    r"(?:不要|不用|不想要?|不需要|不打算|不願意?|不愿意?)"
    r"(?:再|去|參加|参加|進行|进行|申請|申请|辦理|办理|這個|这个|這次|这次|填寫|填写){0,2}"
    + _CHINESE_TRIGGER + "|" + _CHINESE_TRIGGER
    + r"(?:就)?(?:不要|不用|不需要|算了)(?:了|啦|吧)?"
)
_NEGATED_ENGLISH = re.compile(
    r"\b(?:don't|do\s+not|not|no)\s+"
    r"(?:(?:want|need|to|register|for|a|any|the|interested|in)\s+){0,7}"
    r"(?:private[\s-]+tour|guided[\s-]+tour[\s-]+registration)\b", re.I
)
_CANCEL_TOUR = re.compile(
    r"(?:取消|撤回|停止)(?:我的|這個|这个|這次|这次)?"
    r"(?:私人導覽(?:報名)?|私人导览(?:报名)?|專人導覽報名|专人导览报名|"
    r"導覽報名|导览报名|報名導覽|报名导览|預約導覽|预约导览|導覽|导览)"
)
_CANCEL_ENGLISH = re.compile(
    r"\b(?:cancel|stop|withdraw)(?:\s+(?:my|the|this))?\s+"
    r"(?:private[\s-]+tour|guided[\s-]+tour(?:[\s-]+registration)?)\b", re.I
)
_SHORT_CANCEL = {"取消報名", "取消报名", "算了", "不用", "不要"}
_CLEAR_COMMANDS = {"清除對話", "清除对话"}
_PHONE = re.compile(r"\+?\d(?:[\d ()\-]*\d)?")
_CONTACT_PREFIX = re.compile(
    r"(?:電話|电话|手機|手机|聯絡號碼|联络号码|phone|mobile)", re.I
)
_NAME_ONLY = re.compile(r"(?:我的(?:姓名|名字)(?:是|為|为)|我叫)\s*\S+")
_COMMON_SURNAMES = frozenset(
    "王李張张劉刘陳陈楊杨黃黄趙赵吳吴周徐孫孙馬马朱胡郭何高林羅罗鄭郑"
    "梁謝谢宋唐許许韓韩馮冯鄧邓曹彭曾蕭萧田董袁潘于余葉叶蔣蒋杜蘇苏魏"
    "程呂吕丁沈任姚盧卢傅鍾钟姜崔譚谭廖范汪陸陆金石戴賈贾韋韦邱侯江顧顾"
    "尹薛段雷黎史龍龙陶賀贺毛郝秦白方康蔡廖卓賴赖洪溫温武邵龔龚易常安"
)
_ORDINARY_SHORT_WORDS = {"謝謝", "谢谢", "知道", "何時", "何时", "曾經", "曾经", "真的", "早餐", "作品", "好累"}
_SHORT_CHINESE_NAME = re.compile(r"[\u3400-\u9fff]{2,4}")
_DATE_FRAGMENT = r"(?:20\d{2}[-/.年])?\d{1,2}[-/.月]\d{1,2}日?"
_TIME_FRAGMENT = r"(?:[01]?\d|2[0-3])(?:[:點点][0-5]\d(?:分)?|[點点](?:半)?)"
_DATE_OR_TIME = re.compile(
    r"(?:" + _DATE_FRAGMENT + r"(?:[ \t,，]*(?:上午|下午|早上|晚上)?"
    + _TIME_FRAGMENT + r")?|(?:上午|下午|早上|晚上)?" + _TIME_FRAGMENT + r")"
)

_MAX_SESSIONS = 200
_SESSION_TTL_SECONDS = 30 * 60
_active_sessions: OrderedDict[str, float] = OrderedDict()
_state_lock = threading.Lock()


def _session_digest(session_key: str) -> str | None:
    if not isinstance(session_key, str) or not session_key:
        return None
    # Even if the caller passes a LINE identifier, never retain the raw identifier.
    return hashlib.sha256(session_key.encode("utf-8", errors="replace")).hexdigest()


def _purge_expired(now: float) -> None:
    """Caller holds _state_lock; timestamps alone are stored as values."""
    for key, timestamp in list(_active_sessions.items()):
        if now - timestamp >= _SESSION_TTL_SECONDS:
            _active_sessions.pop(key, None)


def _activate(session_key: str) -> None:
    key = _session_digest(session_key)
    if key is None:
        return
    with _state_lock:
        now = time.monotonic()
        _purge_expired(now)
        _active_sessions[key] = now
        _active_sessions.move_to_end(key)
        while len(_active_sessions) > _MAX_SESSIONS:
            _active_sessions.popitem(last=False)


def _is_active(session_key: str) -> bool:
    key = _session_digest(session_key)
    with _state_lock:
        _purge_expired(time.monotonic())
        return key is not None and key in _active_sessions


def clear_session(session_key: str) -> None:
    """Forget only this session's anonymous flag; no submitted data is stored."""
    key = _session_digest(session_key)
    with _state_lock:
        _purge_expired(time.monotonic())
        if key is not None:
            _active_sessions.pop(key, None)


def _field_status(text: str) -> dict[str, bool]:
    fields: dict[str, bool] = {}
    for match in _FIELD_LINE.finditer(text):
        label = _FIELD_ALIASES[match.group(1)]
        fields[label] = bool(match.group(2).strip())
    return fields


def _looks_like_contact_data(text: str) -> bool:
    # No global phone matching: callers must already have an active private flow.
    def phone_length(candidate: str) -> bool:
        return 8 <= sum(char.isdigit() for char in candidate) <= 15

    if _PHONE.fullmatch(text) and phone_length(text):
        return True
    if _CONTACT_PREFIX.search(text):
        if any(phone_length(match.group()) for match in _PHONE.finditer(text)):
            return True
    if _NAME_ONLY.fullmatch(text) or _DATE_OR_TIME.fullmatch(text):
        return True
    # A conservative, deterministic heuristic, not a general PII classifier.
    # Known everyday words still reach the chat engine during an active flow.
    if text not in _ORDINARY_SHORT_WORDS and _SHORT_CHINESE_NAME.fullmatch(text):
        return text[0] in _COMMON_SURNAMES
    if "\n" in text:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return bool(lines) and all(_looks_like_contact_data(line) for line in lines)
    return False


def _reply(message: str) -> list[dict]:
    return [{"type": "text", "text": message}]


def resolve_text(
    text: str, session_key: str = "", *, private_chat: bool = True
) -> list[dict] | None:
    """Resolve tour requests/data before ticket/AI routing, or return None.

    Recognized label payloads take priority over titles and cancellation words in
    values. A completed payload clears the flag; no values are echoed or retained.
    Unrelated topics do not interrupt chat and leave the phone guard until TTL.
    Group/multi-person sources must be passed with private_chat=False.
    """
    if not isinstance(text, str):
        return None
    normalized = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return None
    compact = re.sub(r"\s+", "", normalized).casefold()
    command = compact.rstrip("。.!！?？")
    fields = _field_status(normalized)
    triggered = any(word in compact for word in _KEYWORDS) or bool(_ENGLISH_TRIGGER.search(normalized))
    explicit_cancel = bool(_CANCEL_TOUR.search(compact) or _CANCEL_ENGLISH.search(normalized))

    if not private_chat:
        if fields or triggered or explicit_cancel:
            return _reply(GROUP_MESSAGE)
        if command in _CLEAR_COMMANDS:
            clear_session(session_key)
        return None

    if fields:
        if not any(fields.values()):
            _activate(session_key)
            return _reply(FORM_MESSAGE)
        missing = [label for label in _FIELDS if not fields.get(label, False)]
        if missing:
            _activate(session_key)
            return _reply(
                "還需要補上：" + "、".join(missing)
                + "。請將四項資料填在同一則訊息再回傳，導覽安排仍需另行確認。"
            )
        clear_session(session_key)
        return _reply(COMPLETE_MESSAGE)

    if command in _CLEAR_COMMANDS:
        clear_session(session_key)
        return None  # The chat engine supplies its own clear-conversation reply.

    active = _is_active(session_key)
    if explicit_cancel or (active and command in _SHORT_CANCEL):
        clear_session(session_key)
        return _reply(CANCEL_MESSAGE)
    if triggered and (_NEGATED_CHINESE.search(compact) or _NEGATED_ENGLISH.search(normalized)):
        clear_session(session_key)
        return None
    if triggered:
        _activate(session_key)
        return _reply(FORM_MESSAGE)
    if active and _looks_like_contact_data(normalized):
        return _reply(CONTACT_GUARD_MESSAGE)
    return None

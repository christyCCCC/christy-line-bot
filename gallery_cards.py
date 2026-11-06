"""Approved Christy P gallery content as native LINE Messaging API dictionaries.

Public API: resolve_text, resolve_postback, content_status.  Place artist_cards.json,
artworks_catalog.json and the unmodified about_artist.txt beside this module.
Nothing is sent over the network.  The caller sends returned messages and retains
ownership of chat-engine memory.  An empty session_key deliberately disables
stateful navigation; nonempty keys must be the caller's already-hashed keys.
"""
from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import quote

__all__ = ["resolve_text", "resolve_postback", "content_status"]

_DATA_DIR = Path(__file__).resolve().parent
_IMAGE_BASE = "https://christy-line-bot.onrender.com/static/gallery/"
_VERSION = "artist_works_zh_v2"
_ARTIST_KEYS = ("cover", "who", "age3", "age13", "age16", "series", "philosophy")
_ARTIST_ORDER = ("who", "age3", "age13", "age16", "series", "philosophy")
_TTL_SECONDS = 30 * 60
_MAX_SESSIONS = 500
_MAX_TEXT_UNITS = 5000
_LOCK = threading.RLock()
# No original chat text, LINE IDs, secrets, or content are stored here.
_SESSIONS: OrderedDict[str, dict] = OrderedDict()

_ZH_MAP = str.maketrans({
    "关": "關", "艺": "藝", "术": "術", "绍": "紹", "识": "識",
    "岁": "歲", "画": "畫", "泪": "淚", "养": "養", "爱": "愛",
    "论": "論", "万": "萬", "张": "張", "继": "繼", "续": "續",
    "录": "錄", "让": "讓", "静": "靜", "览": "覽", "谁": "誰",
    "个": "個", "别": "別", "话": "話", "对": "對", "清": "清",
    "从": "從", "时": "時", "么": "麼", "这": "這", "请": "請",
    "说": "說", "开": "開", "与": "與", "为": "為", "学": "學",
    "发": "發", "过": "過", "点": "點", "创": "創", "际": "際",
    "见": "見", "图": "圖", "吗": "嗎", "听": "聽",
    "讲": "講", "获": "獲", "来": "來", "顾": "顧", "题": "題",
    "块": "塊", "颠": "顛", "异": "異", "无": "無", "尽": "盡",
    "梦": "夢", "伤": "傷", "拥": "擁", "护": "護", "恶": "惡",
    "帮": "幫", "烦": "煩", "随": "隨", "荐": "薦", "张": "張", "绘": "繪",
})
_STOP_COMMANDS = {
    "不用了", "停止介紹", "不看了", "回到聊天", "清除對話", "不要介紹了",
    "不用介紹了", "別介紹了", "先不看了", "結束介紹", "停止導覽",
    "stop", "stop introduction", "back to chat", "no thanks", "clear conversation",
    "reset conversation", "stop showing artworks",
}
_NEXT = {"下一件", "下一張", "繼續", "下一個", "下一頁", "繼續介紹", "next", "continue"}
_PREV = {"上一件", "上一張", "上一個", "上一頁", "previous", "prev"}
# Only these ambiguous titles may use an existing artwork browsing context.
_CONTEXT_TITLES = {"讓我安靜一下", "leave me alone", "先別看我", "don't look at me yet"}
# Substantive everyday topics end browsing even if a future title happens to match.
_DAILY_TITLES = {
    "怪物", "monster", "我想安靜", "好累", "so tired", "我好嫉妒", "i am jealous",
    "我十三歲", "我13歲", "我16歲", "我在畫畫", "別人的展覽", "someone else's exhibition",
}
_UNAVAILABLE = "第 11／12 件作品圖片尚未提供。"


@dataclass(frozen=True)
class _Content:
    artists: dict[str, dict]
    works: dict[int, dict]
    about: str


def _read_json(path: Path) -> list:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except (OSError, UnicodeError, ValueError):
        return []


def _read_about() -> str:
    try:
        # newline='' retains the approved original text, including its line endings.
        with (_DATA_DIR / "about_artist_zh.txt").open(encoding="utf-8", newline="") as handle:
            return handle.read()
    except (OSError, UnicodeError):
        return ""


def _safe_filename(value: object) -> bool:
    # Even trusted local JSON cannot accidentally supply a URL or path traversal.
    return (
        isinstance(value, str)
        and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.(?:png|jpe?g)", value, re.I))
        and ".." not in value
    )


def _has_fields(row: object, fields: tuple[str, ...]) -> bool:
    return isinstance(row, dict) and all(
        isinstance(row.get(field), str) and bool(row[field].strip()) for field in fields
    ) and _safe_filename(row.get("image_filename"))


def _load_content() -> _Content:
    # Lazy reads let missing/temporarily replaced files recover without import crashes.
    artists: dict[str, dict] = {}
    works: dict[int, dict] = {}
    for row in _read_json(_DATA_DIR / "artist_cards.json"):
        if _has_fields(row, ("key", "title_zh", "title_en", "image_filename", "text_zh", "text_en")):
            key = row["key"]
            if key in _ARTIST_KEYS and key not in artists:
                artists[key] = dict(row)
    for row in _read_json(_DATA_DIR / "artworks_catalog.json"):
        if not _has_fields(row, ("title_zh", "title_en", "image_filename", "quote_zh", "quote_en", "reading_zh", "reading_en")):
            continue
        raw_id = row.get("id")
        if isinstance(raw_id, bool) or not isinstance(raw_id, (int, str)):
            continue
        if not re.fullmatch(r"[0-9]{1,2}", str(raw_id)):
            continue
        index = int(raw_id)
        if 1 <= index <= 10 and index not in works:
            works[index] = dict(row, id=index)
    return _Content(artists, works, _read_about())


def content_status() -> dict:
    """Only the fixed version and the counts of valid, available approved cards."""
    content = _load_content()
    return {
        "cards_version": _VERSION,
        "content_language": "zh-TW",
        "artist_cards_count": len(content.artists),
        "artwork_cards_count": len(content.works),
    }


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold().translate(_ZH_MAP)
    text = text.replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", text).strip().strip("。！？!?.,，；;：: ")


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _now() -> float:
    return time.monotonic()


def _purge(now: float) -> None:
    expired = [key for key, state in _SESSIONS.items() if now - state["last_seen"] >= _TTL_SECONDS]
    for key in expired:
        _SESSIONS.pop(key, None)
    while len(_SESSIONS) > _MAX_SESSIONS:
        _SESSIONS.popitem(last=False)


def _get_state(session_key: str) -> Optional[dict]:
    _purge(_now())
    state = _SESSIONS.get(session_key) if session_key else None
    return dict(state) if state else None


def _clear(session_key: str) -> None:
    if session_key:
        _SESSIONS.pop(session_key, None)


def _remember(session_key: str, kind: str, position: object) -> None:
    now = _now()
    _purge(now)
    if not session_key:
        return
    state = {"kind": kind, "last_seen": now}
    state["key" if kind == "artist" else "index"] = position
    _SESSIONS[session_key] = state
    _SESSIONS.move_to_end(session_key)
    _purge(now)


def _utf16_len(text: str) -> int:
    return sum(2 if ord(char) > 0xFFFF else 1 for char in text)


def _split_text(text: str) -> list[str]:
    # Do not strip, summarize, or drop any part of the approved source text.
    chunks: list[str] = []
    start = 0
    units = 0
    for offset, char in enumerate(text):
        size = 2 if ord(char) > 0xFFFF else 1
        if units + size > _MAX_TEXT_UNITS:
            chunks.append(text[start:offset])
            start, units = offset, 0
        units += size
    if start < len(text):
        chunks.append(text[start:])
    return chunks


def _button(label: str, data: str) -> dict:
    if _utf16_len(label) > 20:
        raise ValueError("Quick reply labels must fit 20 UTF-16 units")
    return {"type": "action", "action": {"type": "postback", "label": label, "data": data}}


def _roots() -> list[dict]:
    return [_button("作品目錄", "christy_p:artworks"), _button("藝術家故事", "christy_p:about")]


def _artist_buttons(key: str) -> list[dict]:
    items: list[dict] = []
    if key == "cover":
        items.append(_button("下一張", "christy_p:artist:who"))
    elif key in _ARTIST_ORDER:
        index = _ARTIST_ORDER.index(key)
        if index > 0:
            items.append(_button("上一張", "christy_p:artist:" + _ARTIST_ORDER[index - 1]))
        if index + 1 < len(_ARTIST_ORDER):
            items.append(_button("下一張", "christy_p:artist:" + _ARTIST_ORDER[index + 1]))
    items.extend(_roots())
    if key == "who":
        items.append(_button("故事封面", "christy_p:artist:cover"))
    return items


def _work_buttons(index: int, content: _Content) -> list[dict]:
    items: list[dict] = []
    if index > 1 and index - 1 in content.works:
        items.append(_button("上一件", f"christy_p:work:{index - 1}"))
    if index < 10 and index + 1 in content.works:
        items.append(_button("下一件", f"christy_p:work:{index + 1}"))
    return items + _roots()


def _catalog_buttons(content: _Content) -> list[dict]:
    # Fixed short labels cannot overflow even when artwork titles are very long.
    return [_button(f"作品 {index}", f"christy_p:work:{index}") for index in sorted(content.works)] + [
        _button("藝術家介紹", "christy_p:about")
    ]


def _image(row: dict) -> dict:
    # row is selected ONLY through validated trusted JSON keys, never user input.
    url = _IMAGE_BASE + quote(row["image_filename"], safe="._-")
    return {"type": "image", "originalContentUrl": url, "previewImageUrl": url}


def _messages(images: list[dict], text: str, buttons: list[dict]) -> Optional[list[dict]]:
    chunks = _split_text(text)
    if not chunks or len(images) + len(chunks) > 5 or len(buttons) > 13:
        return None
    result = list(images) + [{"type": "text", "text": chunk} for chunk in chunks]
    result[-1]["quickReply"] = {"items": buttons}
    return result


def _chinese_text(row: dict) -> str:
    return row["text_zh"]


def _about(content: _Content) -> Optional[list[dict]]:
    if not content.about.strip() or any(key not in content.artists for key in ("cover", "who")):
        return None
    return _messages([_image(content.artists["cover"]), _image(content.artists["who"])], content.about, _artist_buttons("who"))


def _artist(key: str, content: _Content) -> Optional[list[dict]]:
    row = content.artists.get(key)
    if row is None or (key == "who" and not content.about.strip()):
        return None
    text = content.about if key == "who" else _chinese_text(row)
    return _messages([_image(row)], text, _artist_buttons(key))


def _series(content: _Content) -> Optional[list[dict]]:
    row = content.artists.get("series")
    if row is None or not content.works:
        return None
    detail = _chinese_text(row)
    catalog = "作品目錄\n\n" + "\n".join(
        f"{index}. {work['title_zh']}" for index, work in sorted(content.works.items())
    ) + "\n\n" + _UNAVAILABLE
    buttons = _catalog_buttons(content)
    combined = detail + "\n\n" + catalog
    if _utf16_len(combined) <= _MAX_TEXT_UNITS:
        return _messages([_image(row)], combined, buttons)
    # Keep the narrative and directory separate when a single text cannot fit.
    if _utf16_len(detail) > _MAX_TEXT_UNITS or _utf16_len(catalog) > _MAX_TEXT_UNITS:
        return None  # Never truncate approved content or violate the 3-message limit.
    return [
        _image(row), {"type": "text", "text": detail},
        {"type": "text", "text": catalog, "quickReply": {"items": buttons}},
    ]


def _work(index: int, content: _Content) -> Optional[list[dict]]:
    row = content.works.get(index)
    if row is None:
        return None
    text = (
        f"作品 {index}｜{row['title_zh']}\n\n"
        f"原句\n{row['quote_zh']}\n\n"
        f"作品導讀\n{row['reading_zh']}"
    )
    return _messages([_image(row)], text, _work_buttons(index, content))


def _respond(kind: str, position: object, session_key: str, content: _Content) -> Optional[list[dict]]:
    if kind == "about":
        result = _about(content)
        state_kind, state_position = "artist", "who"
    elif kind == "artist":
        result = _artist(str(position), content)
        state_kind, state_position = "artist", position
    elif kind == "catalog":
        result = _series(content)
        state_kind, state_position = "work", 0
    else:
        result = _work(int(position), content)
        state_kind, state_position = "work", position
    if result is not None:
        _remember(session_key, state_kind, state_position)
    else:
        _clear(session_key)
    return result


def _navigate(state: dict, forward: bool, session_key: str, content: _Content) -> Optional[list[dict]]:
    if state["kind"] == "artist":
        key = state["key"]
        if key == "cover":
            if forward:
                return _respond("artist", "who", session_key, content)
        else:
            index = _ARTIST_ORDER.index(key) + (1 if forward else -1)
            if 0 <= index < len(_ARTIST_ORDER):
                return _respond("artist", _ARTIST_ORDER[index], session_key, content)
        ending = "藝術家故事已到這一端。可選擇作品目錄或重新閱讀。"
    else:
        index = state["index"] + (1 if forward else -1)
        if index in content.works:
            return _respond("work", index, session_key, content)
        if forward and state["index"] == 10:
            ending = "已看完目前提供的 10 件作品。\n\n" + _UNAVAILABLE
        else:
            ending = "目前沒有更多可瀏覽的作品。可選擇作品目錄。"
    _clear(session_key)
    return _messages([], ending, _roots())


def _is_stop(text: str) -> bool:
    if text in _STOP_COMMANDS or _compact(text) in _STOP_COMMANDS:
        return True
    # Explicit rejection of gallery activity, not an incidental negative artwork title.
    if re.search(r"(?:不要|不想|不用|不需要|不必|別|不願|沒有要|沒有想|先不).*(?:介紹|推薦|藝術家|作品|畫作|你的畫|妳的畫|繼續|認識|了解|看圖)", text):
        return True
    return bool(re.search(r"(?:don't|do not|not interested|no need|stop).*(?:artist|artwork|introduc|gallery|show|see)", text))


def _natural_request(text: str) -> str:
    """Normalize polite request framing, not arbitrary words inside a sentence."""
    if not re.search(r"[\u4e00-\u9fff]", text):
        return re.sub(r"^(?:(?:please|can you|could you|would you|will you)\s+)+", "", text)
    body = _compact(text)
    prefix = re.compile(r"^(?:麻煩你|麻煩妳|麻煩|請問|可不可以|能不能|可以|能否|請|幫我|替我|給我|我想要|我想|那麼|那|(?:你|妳)(?!的|是))")
    for _ in range(10):
        match = prefix.match(body)
        if not match:
            break
        body = body[match.end():]
    return re.sub(r"(?:看看|看一下|好嗎|可以嗎|嗎|呢|吧|喔|哦|啦|啊)+$", "", body)


def _sample_work_request(text: str, state: Optional[dict], content: _Content) -> Optional[int]:
    """A request for one unspecified painting opens a real approved example."""
    compact = _compact(text)
    chinese = re.fullmatch(
        r"(?:隨便|隨機|任選)?(?:介紹|推薦|挑|挑選|選|看看|看|帶我看)(?:一下)?"
        r"(?:隨便|隨機)?(?:一(?:張|幅|件|個)|任一(?:張|幅|件)|這(?:張|幅|件)|那(?:張|幅|件))"
        r"(?:你們的|你的|妳的|christyp的)?(?:作品|畫作|畫|繪畫作品)", compact,
    )
    english = re.fullmatch(
        r"(?:introduce|recommend|show me|tell me about|pick|choose) (?:a|one|any|a random) "
        r"(?:(?:of )?your )?(?:artwork|painting|work|piece)(?: for me)?", text,
    )
    if not (chinese or english) or not content.works:
        return None
    if re.search(r"這(?:張|幅|件)|那(?:張|幅|件)", compact) and state and state['kind'] == 'work' and state['index'] in content.works:
        return state['index']
    return min(content.works)


def _is_about(text: str) -> bool:
    compact = _compact(text)
    if compact in {"1", "關於藝術家", "藝術家介紹", "藝術家故事", "關於christyp", "christyp是誰", "誰是christyp", "這位藝術家是誰"}:
        return True
    if re.fullmatch(r"(?:我想知道|想知道|知道|請問)?(?:christyp|這位藝術家|藝術家)是誰(?:嗎|呢)?", compact):
        return True
    if re.fullmatch(
        r"(?:請|可以|能不能|可不可以|我可以|我想要|我想|想要|想)?(?:請)?"
        r"(?:了解|認識|介紹|知道)(?:一下)?"
        r"(?:這位藝術家|藝術家christyp|藝術家|christyp)(?:的故事|的介紹)?(?:一下)?(?:嗎|呢|吧)?",
        compact,
    ):
        return True
    return bool(re.fullmatch(
        r"(?:who is christy\s*p|who's christy\s*p|about (?:the )?artist|artist introduction|"
        r"(?:please )?(?:tell me about|introduce|show me|i want to know|i want to learn about|learn about) (?:the artist|christy\s*p))",
        text,
    ))


def _is_catalog(text: str) -> bool:
    compact = _compact(text)
    if compact in {"2", "作品", "畫作", "作品集", "繪畫作品", "作品系列", "作品介紹", "作品目錄", "萬物可愛論", "everythingiscute"}:
        return True
    if re.fullmatch(
        r"(?:請|可以|能不能|可不可以|我想要|我想|想要|想)?(?:請)?"
        r"(?:看|看看|了解|介紹|認識)(?:一下)?"
        r"(?:christyp的|你們的|你的|妳的)?[《〈「『]?(?:作品|畫作|作品集|作品系列|作品目錄|萬物可愛論)[》〉」』]?(?:一下)?(?:嗎|呢|吧)?", compact,
    ):
        return True
    return bool(re.fullmatch(
        r"(?:artworks?|artwork catalogue|artwork catalog|works catalogue|works catalog|"
        r"(?:please )?(?:show me|i want to see|introduce|tell me about) (?:the )?(?:artworks?|works|everything is cute))",
        text,
    ))


def _work_request(text: str, state: Optional[dict], content: _Content) -> Optional[int]:
    compact = _compact(text)
    ordinal = re.fullmatch(r"(?:請)?(?:介紹|想看|我想看|看看|看)?第(一|二|三|四|五|六|七|八|九|十)件(?:作品)?", compact)
    if ordinal:
        index = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}[ordinal.group(1)]
        return index if index in content.works else None
    match = re.fullmatch(r"(?:請)?(?:介紹|想看|我想看|看看|看)?(?:第0*([0-9]+)件(?:作品)?|作品0*([0-9]+)|work0*([0-9]+))", compact)
    if match:
        digits = next(group for group in match.groups() if group is not None).lstrip("0") or "0"
        if len(digits) > 2:
            return None
        index = int(digits)
        return index if index in content.works else None
    candidate = text
    explicit = False
    chinese = re.match(r"^(?:請)?(?:介紹|我想看|想看|我想了解|想了解|看看|看)(?:一下)?(?:作品)?\s*", candidate)
    if chinese:
        candidate, explicit = candidate[chinese.end():], True
    elif candidate.startswith("作品"):
        candidate, explicit = candidate[2:], True
    else:
        english = re.match(r"^(?:please )?(?:show me|introduce|tell me about|i want to see|artwork|work)\s+", candidate)
        if english:
            candidate, explicit = candidate[english.end():], True
    candidate = _norm(candidate.strip(" 《》〈〉「」『』\""))
    in_works = bool(state and state["kind"] == "work")
    for index, row in sorted(content.works.items()):
        if _compact(candidate) in {_compact(_norm(row["title_zh"])), _compact(_norm(row["title_en"]))}:
            if candidate in _CONTEXT_TITLES and not (explicit or in_works):
                return None
            if candidate in _DAILY_TITLES and not explicit:
                return None
            return index
    return None


def _artist_question(text: str, state: Optional[dict]) -> Optional[str]:
    compact = _compact(text)
    pointed = bool(re.search(r"christyp|藝術家|妳的(?:創作|繪畫)", compact))
    if not pointed and not (state and state["kind"] == "artist"):
        return None
    # Closed question forms prevent the user's age/emotions from becoming biography.
    body = re.sub(r"^(?:請介紹|介紹|想了解|我想了解|請問)", "", compact)
    body = re.sub(r"^(?:christyp|這位藝術家|藝術家)(?:的)?", "", body)
    body = re.sub(r"^妳的", "", body)
    body = re.sub(r"(?:嗎|呢|吧)$", "", body)
    forms = {
        "age3": r"(?:創作起點(?:是什麼)?|繪畫起點(?:是什麼)?|童年的美術訓練|(?:三歲|3歲)(?:(?:怎麼|如何)(?:開始)?(?:畫畫|繪畫|創作)|的故事)?)",
        "age13": r"(?:眼睛與淚水|眼睛和淚水|眼睛與淚水的意義|眼睛和淚水的意義|(?:十三歲|13歲)(?:的故事|發生了什麼|怎麼了)?)",
        "age16": r"(?:(?:十六歲|16歲)(?:(?:如何|怎麼)(?:養活自己|生活|開始工作)|的故事)?)",
        "philosophy": r"(?:創作理念|創作哲學|藝術理念)",
    }
    for key, pattern in forms.items():
        if re.fullmatch(pattern, body):
            return key
    return None


def resolve_text(text: str, session_key: str = "") -> Optional[list[dict]]:
    """Return native LINE messages for explicit gallery intent, otherwise None.

    A substantive unmatched turn or an explicit opt-out clears only gallery state.
    The caller should pass None to its normal chat engine and separately synchronize
    any chat-engine browsing memory; this module never accesses that memory.
    """
    with _LOCK:
        state = _get_state(session_key)
        if not isinstance(text, str) or not text.strip():
            return None
        normalized = _norm(text)
        if _is_stop(normalized):
            _clear(session_key)
            return None
        content = _load_content()
        requested = _natural_request(normalized)
        if _is_about(requested):
            return _respond("about", None, session_key, content)
        sample = _sample_work_request(requested, state, content)
        if sample is not None:
            return _respond("work", sample, session_key, content)
        if _is_catalog(requested):
            return _respond("catalog", None, session_key, content)
        if requested in _NEXT | _PREV:
            return _navigate(state, requested in _NEXT, session_key, content) if state else None
        index = _work_request(requested, state, content)
        if index is not None:
            return _respond("work", index, session_key, content)
        key = _artist_question(requested, state)
        if key is not None:
            return _respond("artist", key, session_key, content)
        _clear(session_key)
        return None


def resolve_postback(data: str, session_key: str = "") -> Optional[list[dict]]:
    """Resolve only exact allowlisted postback payloads. Never interpolate URLs."""
    with _LOCK:
        _get_state(session_key)  # Apply TTL even to invalid/non-gallery actions.
        if not isinstance(data, str):
            _clear(session_key)
            return None
        content = _load_content()
        if data == "christy_p:about":
            return _respond("about", None, session_key, content)
        if data == "christy_p:artworks":
            return _respond("catalog", None, session_key, content)
        artist_match = re.fullmatch(r"christy_p:artist:(cover|who|age3|age13|age16|series|philosophy)", data)
        if artist_match:
            return _respond("artist", artist_match.group(1), session_key, content)
        work_match = re.fullmatch(r"christy_p:work:([1-9]|10)", data)
        if work_match:
            return _respond("work", int(work_match.group(1)), session_key, content)
        _clear(session_key)
        return None

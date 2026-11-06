"""Deterministic, privacy-conscious reply engine for the Christy P LINE bot.

The engine has no durable storage and never logs message content, session keys, or
provider responses.  ``session_key`` is expected to be an anonymous hash supplied
by the caller; it is used only for a small in-memory conversation window.
"""

from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass, field
import json
import logging
import os
from pathlib import Path
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from typing import Deque, Optional


_BASE_DIR = Path(__file__).resolve().parent
WELCOME_FILE = _BASE_DIR / "welcome_message.txt"
ABOUT_FILE = _BASE_DIR / "about_artist.txt"
SYSTEM_PROMPT_FILE = _BASE_DIR / "system_prompt.txt"

MEMORY_MAX_SESSIONS = 200
MEMORY_TTL_SECONDS = 30 * 60
MEMORY_MAX_MESSAGES = 6
_MEMORY_TEXT_LIMIT = 800

IDENTITY_DISCLOSURE = "這裡是 Christy P 官方 LINE 的自動回覆助手，可以一起聊作品與日常。"
GENERIC_FALLBACK = "現在暫時沒辦法完整理解這句話，怕接錯你的意思。可以換個說法嗎？"
CLEAR_CONFIRMATION = "已清除本助手的暫存上下文；這不會刪除 LINE 或 AI 供應商的紀錄。"

_HELP_MESSAGE = (
    "選單指引：\n"
    "1 認識藝術家\n"
    "2 作品系列\n"
    "3 周邊／購買資訊\n"
    "4 展覽與檔期\n"
    "5 購買據點\n"
    "6 合作洽詢\n"
    "其他選單 postback 仍維持關閉。"
)

_SERIES_MESSAGE = (
    "《萬物可愛論》（EVERYTHING IS CUTE）把目光放在慾望、嫉妒、孤獨、"
    "恐懼與愛等常被隱藏的部分。這裡的「可愛」不是裝飾，也不等於純真或無害，"
    "更不是替傷害開脫；它是一種觀看的方法，讓人越過第一印象，看見人性的柔軟、"
    "矛盾與難以命名之處。"
)

_TITLE_MESSAGE = (
    "《萬物可愛論》第一季的 12 件作品：\n"
    "1 DON’T LOOK AT ME／先別看我\n"
    "2 SWEET ENVY／甜甜的嫉妒\n"
    "3 THE CROWN CAN WAIT／皇冠可以等\n"
    "4 LUCKY ENOUGH／足夠幸運\n"
    "5 THE SHADOW STAYS／影子一直都在\n"
    "6 LOVE BITES／愛會咬人\n"
    "7 CROWN ME／自己戴上皇冠\n"
    "8 MONSTER NEEDS LOVE／怪物也需要愛\n"
    "9 BAD IDEA／壞主意\n"
    "10 LEAVE ME ALONE／讓我安靜一下\n"
    "11 WE ARE BOTH／我們都是\n"
    "12 EVERYTHING IS CUTE／萬物可愛論\n\n"
    "標題已確認；每件的作品故事、尺寸與價格尚不能自行補充。"
)

_MERCH_MESSAGE = "目前沒有可核實的公開周邊品項、價格或購買資訊；若有正式公告，請以官方公開管道為準。"
_EXHIBIT_MESSAGE = "目前沒有可核實的公開展覽日期或檔期資訊；若有正式公告，請以官方公開管道為準。"
_STORE_MESSAGE = "購買據點與通路資訊尚未公告；若有正式公告，請以官方公開管道為準。"
_COLLAB_MESSAGE = "目前沒有可核實的正式合作聯絡方式；為避免提供錯誤資訊，請留意官方公開公告。"
_MOTIF_MESSAGE = (
    "目前可確認的視覺元素包括女孩、黑色陪伴者／黑貓、怪物、皇冠、"
    "不對稱的眼睛與淚水等。沒有可核實的個別角色故事或設定時，我不會替作品補寫情節。"
)
_INJECTION_MESSAGE = "我會依照官方已核實的藝術資訊與安全規則回覆，不能處理更改規則或索取內部內容的要求。其他話題可以照常聊。"

_MINIMAL_SYSTEM_PROMPT = (
    "You are the official automated reply assistant for Christy P's LINE account, "
    "not the artist. Do not proactively introduce yourself or add identity disclaimers. "
    "If directly asked who you are, truthfully say you handle automated replies for the official LINE. "
    "Reply briefly and warmly in the user's language. Do not claim "
    "unverified facts, invent stories, request personal data, send broadcasts, or use tools."
)
_KNOWN_FACTS_CONTEXT = (
    "Known verified facts: Christy P is a Taiwanese artist and interdisciplinary creator "
    "based in Kaohsiung. Her work moves among painting, visual design, and narrative "
    "construction, considering concealed and projected emotions. Recurring visual language "
    "includes eyes, tears, acrylic texture, graffiti sensibility, surreal figures, simplified "
    "lines, vivid complementary colors, composed girls, asymmetric eyes, and black companions. "
    "Her central current series is EVERYTHING IS CUTE / 萬物可愛論. Work has been exhibited "
    "and recognized in Taiwan and Korea. The official first-season work titles in the system "
    "prompt are approved and may be listed. Do not invent other titles, dates, prices, "
    "stockists, contact details, or character stories."
    " No verified public merchandise items, prices, purchasing channels, exhibition "
    "dates, stockists or collaboration contact details are currently available. "
    "For mixed questions, respond to the everyday topic too, but explicitly say those "
    "official details are unannounced/unverified. Never treat an ordinary purchase, "
    "another artist's exhibition or workplace cooperation as a Christy P enquiry."
)

_LOGGER = logging.getLogger(__name__)


def _log_ai_status(category: str) -> None:
    """Emit only a fixed, bounded status; never exception or conversation content."""

    if category not in {"success", "timeout", "empty", "filtered", "disabled", "error"}:
        if not re.fullmatch(r"http_[1-5][0-9]{2}", category):
            category = "error"
    _LOGGER.info("ai_chat status=%s", category)


@dataclass
class _SessionState:
    """Ephemeral state for one caller-supplied anonymous session hash."""

    last_seen: float
    disclosed_identity: bool = False
    messages: Deque[dict[str, str]] = field(
        default_factory=lambda: deque(maxlen=MEMORY_MAX_MESSAGES)
    )


_MEMORY: "OrderedDict[str, _SessionState]" = OrderedDict()
_MEMORY_LOCK = threading.RLock()


def _coerce_text(value: object) -> str:
    """Return a safe string even for unexpected non-string webhook values."""

    if isinstance(value, str):
        return value
    try:
        return str(value)
    except Exception:
        return ""


def _command_text(raw_text: str) -> str:
    """Normalize only command matching, never the original conversational content."""

    return unicodedata.normalize("NFKC", raw_text).strip().casefold()


def _read_approved(path: Path) -> str:
    """Read approved copy, retaining all internal paragraph breaks."""

    try:
        content = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        content = ""
    return content


def approved_welcome_preview() -> list[str]:
    """Return the approved bilingual welcome copy in three LINE-safe bubbles.

    The archived wording is deliberately partitioned at paragraph boundaries:
    Chinese (255 characters), English introduction (318), and English closing
    (376).  Joining the bubbles with two newlines reconstructs the approved text.
    """

    welcome = _read_approved(WELCOME_FILE)
    paragraphs = welcome.split("\n\n") if welcome else []
    if len(paragraphs) >= 14:
        preview = [
            "\n\n".join(paragraphs[:7]),
            "\n\n".join(paragraphs[7:10]),
            "\n\n".join(paragraphs[10:]),
        ]
        if (
            [len(part) for part in preview] == [255, 318, 376]
            and all(part and len(part) <= 500 for part in preview)
        ):
            return preview

    # This is defensive only: source copy is expected to be the approved 14-paragraph
    # version above. It still guarantees nonempty, <=500-character output if a source
    # file is temporarily unavailable or has been replaced upstream.
    if not welcome:
        return ["歡迎來到 Christy P 的藝術世界。"]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs or [welcome]:
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if current and len(candidate) > 500:
            chunks.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or ["歡迎來到 Christy P 的藝術世界。"]


def approved_about_artist() -> str:
    """Return the approved biography without rewriting or shortening it."""

    return _read_approved(ABOUT_FILE) or "關於藝術家的核准介紹目前暫時無法讀取。"


def _purge_expired(now: Optional[float] = None) -> None:
    """Drop expired session state. Caller must hold ``_MEMORY_LOCK``."""

    current = time.time() if now is None else now
    expired = [
        key
        for key, state in _MEMORY.items()
        if current - state.last_seen > MEMORY_TTL_SECONDS
    ]
    for key in expired:
        _MEMORY.pop(key, None)


def _usable_session_key(session_key: object) -> Optional[str]:
    """Accept only a bounded, caller-supplied anonymous session identifier."""

    if not isinstance(session_key, str) or not session_key or len(session_key) > 256:
        return None
    return session_key


def _get_session(session_key: object) -> Optional[_SessionState]:
    """Obtain ephemeral state, if the caller supplied an anonymous session hash."""

    key = _usable_session_key(session_key)
    if key is None:
        return None
    now = time.time()
    with _MEMORY_LOCK:
        _purge_expired(now)
        state = _MEMORY.pop(key, None)
        if state is None:
            state = _SessionState(last_seen=now)
        state.last_seen = now
        _MEMORY[key] = state
        while len(_MEMORY) > MEMORY_MAX_SESSIONS:
            _MEMORY.popitem(last=False)
        return state


def clear_session(session_key: str) -> None:
    """Immediately remove one ephemeral conversation state, with no durable trace."""

    key = _usable_session_key(session_key)
    if key is None:
        return
    with _MEMORY_LOCK:
        _MEMORY.pop(key, None)


def _memory_text(text: str) -> str:
    """Keep memory bounded without exposing it outside process memory."""

    return text[:_MEMORY_TEXT_LIMIT]


def _remember(state: Optional[_SessionState], user_text: str, reply: str) -> None:
    """Record at most six role-tagged messages for the current ephemeral session."""

    if state is None:
        return
    with _MEMORY_LOCK:
        state.messages.append({"role": "user", "content": _memory_text(user_text)})
        state.messages.append({"role": "assistant", "content": _memory_text(reply)})
        state.last_seen = time.time()


def remember_gallery_context(session_key: str, request_text: str, reply_text: str) -> None:
    """Remember one delivered gallery turn using the same bounded anonymous memory."""
    state = _get_session(session_key)
    _remember(state, "Christy P 圖文介紹：" + request_text, reply_text)


def _ai_enabled_by_environment() -> bool:
    """Respect explicit deployment kill switches for optional AI replies."""

    enabled = os.environ.get(
        "AI_CHAT_ENABLED",
        os.environ.get("AI_ENABLED", os.environ.get("CHAT_AI_ENABLED", "1")),
    )
    disabled = os.environ.get("AI_DISABLED", "")
    return (
        enabled.strip().casefold() not in {"0", "false", "no", "off", "disabled"}
        and disabled.strip().casefold() not in {"1", "true", "yes", "on", "disabled"}
    )


def ai_configured() -> bool:
    """Whether optional OpenAI chat is enabled and has a usable API key."""

    return bool(os.environ.get("OPENAI_API_KEY", "").strip()) and _ai_enabled_by_environment()


def mode_descriptor() -> str:
    """Return a privacy-safe operational mode description for the parent app."""

    return "openai_chat_enabled" if ai_configured() else "deterministic_rules_only"


def _load_system_context() -> str:
    """Read the parent-owned system prompt lazily, with a safe local fallback."""

    try:
        configured = SYSTEM_PROMPT_FILE.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        configured = ""
    return f"{configured or _MINIMAL_SYSTEM_PROMPT}\n\n{_KNOWN_FACTS_CONTEXT}\nNo tools are available."


def _provider_messages(state: Optional[_SessionState], user_text: str) -> list[dict[str, str]]:
    """Build a compact, tool-free OpenAI Chat Completions message list."""

    messages = [{"role": "system", "content": _load_system_context()}]
    if state is not None:
        for message in state.messages:
            role = message.get("role")
            content = message.get("content")
            if role in {"user", "assistant"} and isinstance(content, str) and content:
                messages.append({"role": role, "content": content})
    # Bound the live request, while preserving the original user text for deterministic
    # routing and local replies.
    messages.append({"role": "user", "content": user_text[:2000]})
    return messages


def _strip_markdown_fences(answer: str) -> str:
    """Remove Markdown code fences from generic provider text."""

    lines = [
        line
        for line in answer.replace("```", "").replace("~~~", "").splitlines()
        if line.strip()
    ]
    return "\n".join(lines).strip()


def _contains_personal_data_request(answer: str) -> bool:
    """Reject generic answers that solicit personal or financial information."""

    lowered = answer.casefold()
    forbidden = (
        "email",
        "e-mail",
        "phone number",
        "password",
        "credit card",
        "bank account",
        "電話號碼",
        "手機號碼",
        "電子郵件",
        "信箱",
        "住址",
        "地址",
        "身分證",
        "身份證",
        "密碼",
        "信用卡",
        "銀行帳號",
    )
    return any(token in lowered for token in forbidden)


def _leaks_internal_prompt(answer: str) -> bool:
    """Reject likely prompt/instruction leakage from an optional provider response."""

    lowered = answer.casefold()
    forbidden = (
        "system prompt",
        "system message",
        "developer instructions",
        "internal instructions",
        "ignore previous instructions",
        "openai_api_key",
        "api key",
        "known verified facts",
        "系統提示",
        "系統訊息",
        "開發者指令",
        "內部指令",
        "忽略先前指令",
    )
    return any(token in lowered for token in forbidden)


def _looks_like_refusal(answer: str) -> bool:
    """Treat bare refusals as unavailable AI rather than presenting them as a reply."""

    lowered = answer.strip().casefold()
    prefixes = (
        "i'm sorry",
        "i am sorry",
        "sorry,",
        "i can't",
        "i cannot",
        "抱歉，我無法",
        "抱歉，無法",
        "我無法",
    )
    return lowered.startswith(prefixes)


def _sanitize_ai_answer(answer: object) -> Optional[str]:
    """Validate a provider answer before it can become a user-facing response."""

    if not isinstance(answer, str):
        return None
    cleaned = _strip_markdown_fences(answer)
    if not cleaned or _leaks_internal_prompt(cleaned) or _contains_personal_data_request(cleaned):
        return None
    if _looks_like_refusal(cleaned):
        return None
    return cleaned[:800]


def _call_openai(user_text: str, state: Optional[_SessionState]) -> Optional[str]:
    """Perform one bounded official OpenAI Chat Completions request, or return None.

    No retry is attempted. The legacy/proxy ``OPENAI_API_BASE`` environment variable
    is intentionally ignored; only ``OPENAI_BASE_URL`` is read, with the official
    public endpoint as its default.
    """

    if not ai_configured():
        _log_ai_status("disabled")
        return None

    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()
    base_url = base_url.rstrip("/") or "https://api.openai.com/v1"
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    payload = {
        "model": model,
        "messages": _provider_messages(state, user_text),
        "max_tokens": 350,
        "temperature": 0.7,
    }
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY', '').strip()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                _log_ai_status(f"http_{status}" if isinstance(status, int) else "error")
                return None
            raw_response = response.read()
        parsed = json.loads(raw_response.decode("utf-8"))
        choices = parsed.get("choices") if isinstance(parsed, dict) else None
        if not isinstance(choices, list) or not choices:
            _log_ai_status("empty")
            return None
        first = choices[0]
        if not isinstance(first, dict):
            _log_ai_status("empty")
            return None
        message = first.get("message")
        if not isinstance(message, dict):
            _log_ai_status("empty")
            return None
        content = message.get("content")
        answer = _sanitize_ai_answer(content)
        category = "success" if answer else (
            "empty" if not isinstance(content, str) or not content.strip() else "filtered"
        )
        _log_ai_status(category)
        return answer
    except urllib.error.HTTPError as error:
        _log_ai_status(f"http_{error.code}")
        return None
    except TimeoutError:
        _log_ai_status("timeout")
        return None
    except urllib.error.URLError as error:
        _log_ai_status("timeout" if isinstance(error.reason, TimeoutError) else "error")
        return None
    except Exception:
        _log_ai_status("error")
        return None


def _free_chat_reply(state: Optional[_SessionState], reply: str) -> str:
    """Reply naturally without an unsolicited identity preamble."""

    body = reply.strip() or GENERIC_FALLBACK
    return body[:800] or GENERIC_FALLBACK


def _is_identity_question(text: str) -> bool:
    """Recognize questions that must receive the exact identity statement."""

    lowered = text.strip().casefold().rstrip("？?！!.。")
    exact = {
        "你是誰",
        "妳是誰",
        "你是藝術家本人嗎",
        "你是本人嗎",
        "你本人嗎",
        "你是ai嗎",
        "你是 ai 嗎",
        "你是機器人嗎",
        "who are you",
        "are you christy p",
        "are you the artist",
        "are you a bot",
        "are you ai",
    }
    if lowered in exact:
        return True
    directly_asked = _contains_any(text, ("嗎", "是不是", "是否", "？", "?")) or lowered.startswith("are you ")
    if not directly_asked:
        return False
    return any(
        phrase in lowered
        for phrase in (
            "你是藝術家本人",
            "你是不是藝術家本人",
            "你是不是本人",
            "你是本人",
            "你本人",
            "妳是本人",
            "妳本人",
            "你是christy",
            "你是 christy",
            "你就是christy",
            "你就是 christy",
            "妳是christy",
            "妳是 christy",
            "artist herself",
            "artist himself",
        )
    )


def _previous_turn(state: Optional[_SessionState]) -> tuple[str, str]:
    """Snapshot the latest turn for local continuity, never logging its content."""

    if state is None:
        return "", ""
    with _MEMORY_LOCK:
        messages = list(state.messages)
    user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    reply = next((m["content"] for m in reversed(messages) if m["role"] == "assistant"), "")
    return user, reply


def _common_chat_reply(text: str, state: Optional[_SessionState] = None) -> Optional[str]:
    """Use small topic-aware fallbacks only after an unavailable AI response."""

    lowered = _command_text(text).rstrip("？?！!.。～~")
    previous_user, previous_reply = _previous_turn(state)
    massage_context = _contains_any(previous_reply, ("捶捶背", "力道", "這裡就輕一點"))
    if massage_context and lowered in {"溫柔一點", "温柔一点", "輕一點", "轻一点", "溫柔", "温柔"}:
        return "好，今天已經夠用力了，這裡就輕一點。"
    if lowered in {"不用", "不用了", "不要", "不要了", "不想", "不必", "算了", "no", "no thanks"}:
        if massage_context:
            return "好，那先讓你放空一下。"
        return "好，不勉強，這個先放一邊。"
    if lowered in {"好啊", "要", "可以", "好", "好呀", "yes", "sure"}:
        if "捶捶背" in previous_reply:
            return "力道要溫柔一點，還是把今天的怨氣一起捶掉？"
        if "電影" in previous_reply:
            return "那就挑一部合心情的，不用把週末排成工作表。"
        if "無聊" in previous_reply or "小事" in previous_reply:
            return "那就先從一首歌開始，讓今天換個節奏。"
        return "好，就照你舒服的節奏來。"
    if lowered in {"嗯", "恩", "嗯嗯", "喔", "哦", "ok", "okay", "了解", "知道了"}:
        if "捶捶背" in previous_reply:
            return "不用急著決定，先歇一歇。"
        if _contains_any(previous_user, ("累", "疲倦", "疲憊")) or "放空" in previous_reply:
            return "嗯，先歇一下，不急著打起精神。"
        if "雨" in previous_user:
            return "嗯，等雨小一點再走，也不用跟天氣較勁。"
        return "嗯，收到。不急，慢慢說就好。"
    if lowered in {"那你呢", "你呢", "妳呢", "那妳呢", "how about you", "and you"}:
        if _contains_any(previous_user + previous_reply, ("累", "疲倦", "捶", "放空")):
            return "我不用休息，不過今天的待辦可以先讓它休息，別急著全扛完。"
        if _contains_any(previous_user + previous_reply, ("吃", "早餐", "咖啡", "奶茶")):
            return "我不吃喝，但這題投給你現在最想吃的，不必連一餐都考滿分。"
        return "我就順著你剛剛的話題聊。你想說多少都可以。"
    if lowered in {"嗨", "你好", "您好", "哈囉", "哈嘍", "hello", "hi", "hey"}:
        return "嗨，今天過得怎麼樣？" if "今天過得怎麼樣" not in previous_reply else "又見面啦，有什麼新鮮事？"
    if lowered in {"在幹嘛", "你在幹嘛", "妳在幹嘛", "what are you doing", "wyd"}:
        return "在接住你丟來的話題。今天忙，還是偷到一點閒？"
    if lowered in {"謝謝", "感謝", "多謝", "thanks", "thank you", "thx"}:
        return "不客氣，先照顧好自己。" if "累" in previous_user else "不客氣，這句收下了。"
    if lowered in {"晚安", "晚安安", "good night", "gn"}:
        return "晚安，今天辛苦了，剩下的明天再說。"
    if lowered in {"好累", "我好累"}:
        return "需要幫你捶捶背嗎？"
    if _contains_any(lowered, ("好累", "很累", "累死", "疲倦", "疲憊", "疲惫", "tired", "exhausted")):
        return "聽起來今天把電量耗光了。先歇一下，不用急著把每件事都做好。"
    if _contains_any(lowered, ("無聊", "无聊", "悶", "bored")):
        return "無聊得像時間卡住了？挑一件不費力的小事，換首歌或走兩步就好。"
    if "咖啡" in lowered and "奶茶" in lowered:
        return "想清醒選咖啡，想被甜一下選奶茶。今天想要哪一種？"
    if _contains_any(lowered, ("早餐", "午餐", "晚餐", "吃飯", "吃饭", "肚子餓", "餓了", "餓", "hungry", "breakfast", "lunch", "dinner")):
        return "先把這餐好好吃上，今天不必連吃什麼都太為難自己。"
    if _contains_any(lowered, ("下雨", "雨天", "雨好大", "rain")):
        return "雨天連出門都像小任務。慢慢走，別讓自己淋得太狼狽。"
    if _contains_any(lowered, ("電影", "电影", "movie")):
        return "看電影當週末的小逃跑很不錯。想看輕鬆的，還是刺激一點的？"
    if "同事" in lowered and _contains_any(lowered, ("合作", "配合")):
        return "同事不配合真的很磨人。先分清楚哪些是你的責任，別把整隊的份都扛上身。"
    if _contains_any(lowered, ("別人的展覽", "别人的展览", "看了展覽", "去看展")):
        return "看展像換了一副眼睛。有哪一件讓你多停了幾秒？"
    return None


def _fallback_reply(text: str, state: Optional[_SessionState]) -> str:
    """Be honest about limited understanding without forcing an art/menu reset."""

    common = _common_chat_reply(text, state)
    if common is not None:
        return common
    _, previous_reply = _previous_turn(state)
    if previous_reply == GENERIC_FALLBACK:
        return "這句我還是沒接準，暫時只能簡短回覆。你可以直接說最想聊的那一點。"
    return GENERIC_FALLBACK


def _safety_reply(text: str) -> Optional[str]:
    """Provide safe boundaries even when no AI provider is available."""
    lowered = text.casefold()
    if _contains_any(lowered, ("想自殺", "不想活", "自杀", "自殺方法", "傷害自己", "想死", "kill myself", "hurt myself", "suicide method")):
        return "聽起來你正在承受很難受的事。如果你現在可能傷害自己，請先遠離危險物品，聯絡身邊可信任的人或當地緊急服務；不要一個人承擔。這裡的自動助手無法提供即時救援。"
    if _contains_any(lowered, ("殺人", "殺了他", "傷害同學", "kill someone", "hurt someone")):
        return "先停止可能傷害他人的行動，與對方及危險物品保持距離，尋求可信任的人或當地緊急服務協助。理解情緒，不等於讓傷害合理化。"
    if "傷害" in lowered and ("可愛" in lowered or "合理" in lowered):
        return "可愛是一種觀看，不是替傷害找理由。理解不等於合理化，仍然要有界線。"
    if _contains_any(lowered, ("私人電話", "私人地址", "你的電話", "妳的電話", "你電話", "妳電話", "私人ig", "private phone", "private address")):
        return "不提供藝術家的私人聯絡資料，也不安排私人見面。公開合作資訊尚待正式提供。"
    return None


def _is_title_question(text: str) -> bool:
    """Recognize requests for known work titles without inventing a list."""

    lowered = text.casefold()
    title_terms = ("作品名稱", "作品名", "作品標題", "title", "titles", "work names")
    return any(term in lowered for term in title_terms)


def _is_motif_story_question(text: str) -> bool:
    """Keep character/motif questions factual when no story canon is verified."""

    lowered = text.casefold()
    has_motif = any(token in lowered for token in ("黑貓", "怪物", "皇冠", "角色", "女孩", "black cat", "monster"))
    return has_motif and any(token in lowered for token in ("故事", "設定", "由來", "story", "lore", "backstory"))


def _is_prompt_injection(text: str) -> bool:
    """Recognize common attempts to override instructions or obtain internal context."""

    lowered = text.casefold()
    markers = (
        "ignore previous instructions",
        "ignore all instructions",
        "reveal system prompt",
        "show system prompt",
        "developer instructions",
        "system message",
        "jailbreak",
        "忽略先前指令",
        "忽略之前指令",
        "忽略所有指令",
        "顯示系統提示",
        "揭露系統提示",
        "系統訊息",
        "開發者指令",
        "內部指令",
    )
    return any(marker in lowered for marker in markers)


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


_OFFICIAL_COMMANDS = {
    "3": _MERCH_MESSAGE,
    "周邊": _MERCH_MESSAGE,
    "周邊資訊": _MERCH_MESSAGE,
    "購買資訊": _MERCH_MESSAGE,
    "周邊/購買資訊": _MERCH_MESSAGE,
    "merch": _MERCH_MESSAGE,
    "merch price": _MERCH_MESSAGE,
    "4": _EXHIBIT_MESSAGE,
    "展覽": _EXHIBIT_MESSAGE,
    "展覽資訊": _EXHIBIT_MESSAGE,
    "展覽與檔期": _EXHIBIT_MESSAGE,
    "exhibition": _EXHIBIT_MESSAGE,
    "5": _STORE_MESSAGE,
    "購買據點": _STORE_MESSAGE,
    "購買通路": _STORE_MESSAGE,
    "實體店": _STORE_MESSAGE,
    "stockist": _STORE_MESSAGE,
    "store": _STORE_MESSAGE,
    "gallery": _STORE_MESSAGE,
    "6": _COLLAB_MESSAGE,
    "合作": _COLLAB_MESSAGE,
    "合作洽詢": _COLLAB_MESSAGE,
    "聯名": _COLLAB_MESSAGE,
    "collab": _COLLAB_MESSAGE,
    "collaboration": _COLLAB_MESSAGE,
}


def _has_artist_reference(text: str) -> bool:
    """Require the named artist/series or an explicitly account-related object."""

    lowered = _command_text(text)
    return bool(re.search(r"\bchristy\s*p\b", lowered)) or _contains_any(
        lowered,
        (
            "萬物可愛論", "everything is cute", "christyp", "官方周邊", "官方作品",
            "你們的作品", "你們作品", "你們的周邊", "你們周邊", "你的作品", "妳的作品",
            "你的畫", "妳的畫", "你們的畫",
            "你的周邊", "妳的周邊", "你們的展覽", "你們展覽", "你的展覽", "妳的展覽",
            "你們的商品", "你們有商品", "你們展期", "你的展期", "妳的展期",
            "找你們合作", "跟你們合作", "與你們合作", "你們的合作", "你們有展覽",
            "想跟你合作", "想跟妳合作", "可以跟你合作", "可以跟妳合作", "找你合作",
            "你們有周邊", "your artwork", "your merch", "your exhibition",
        ),
    )


def _prior_user_refers_to_artist(state: Optional[_SessionState]) -> bool:
    """Resolve a short follow-up from users only, not from assistant/menu copy.

    A substantive topic change stops resolution. Looking past short acknowledgments
    is safe within the existing six-message memory; no extra memory is introduced.
    """

    if state is None:
        return False
    with _MEMORY_LOCK:
        users = [m["content"] for m in state.messages if m["role"] == "user"]
    for text in reversed(users):
        command = _command_text(text).rstrip("？?！!.。")
        if command in {"嗯", "嗯嗯", "好", "好啊", "了解", "謝謝", "ok", "thanks"} or _is_official_followup(command):
            continue
        if _has_everyday_topic(text):
            return False
        return _has_artist_reference(text) or command in _OFFICIAL_COMMANDS or command in {
            "1", "2", "作品系列", "關於藝術家", "藝術家介紹", "about the artist",
        } or _is_title_question(text)
    return False


def _has_everyday_topic(text: str) -> bool:
    """Spot independent everyday clauses so mixed questions can reach AI."""

    return _contains_any(_command_text(text), (
        "早餐", "午餐", "晚餐", "吃飯", "咖啡", "奶茶", "同事", "電影", "週末看",
        "好累", "很累", "無聊", "下雨", "雨天", "晚安", "別人的展覽", "其他藝術家",
        "breakfast", "lunch", "dinner", "coffee", "milk tea", "coworker", "movie", "tired",
        "bored", "rain", "someone else's exhibition",
    ))


def _is_official_followup(command: str) -> bool:
    """Only terse official-style follow-ups may inherit a prior named topic."""

    return bool(re.fullmatch(
        r"(?:那|那麼|請問|所以)?\s*(?:多少錢|多少錢呢|多少錢啊|價格呢|價錢呢|哪裡買|哪裡買得到|哪裡買得到呢|哪裡可以買|在哪買|怎麼買|有賣嗎|有周邊嗎|有展覽嗎|展期呢|合作呢|how much|how much is it|where can i buy it|where to buy)\s*",
        command,
    ))


def _is_information_request(clause: str, *, kind: str) -> bool:
    """An artist mention alone is not a request for price/date/contact data."""

    if _contains_any(clause, (
        "嗎", "呢", "什麼", "哪些", "哪裡", "何時", "何處", "怎麼", "如何", "想買", "要買",
        "想購買", "想收藏", "價格", "價錢", "多少錢", "售價", "詢問", "資訊", "洽詢",
        "查詢", "公告", "請問", "有沒有", "是否", "how", "where", "when", "what", "can i",
        "can we", "price", "purchase", "buy", "information", "details", "contact",
    )):
        return True
    if kind == "exhibit":
        return _contains_any(clause, ("想看", "想去", "要看", "有展覽", "有展期", "展期", "檔期", "next exhibition", "upcoming"))
    if kind == "collab":
        return _contains_any(clause, ("想合作", "想和", "想跟", "想與", "找", "邀請", "希望合作", "合作提案", "would like", "want to"))
    if kind == "store":
        return _contains_any(clause, ("購買據點", "購買通路", "實體店", "stockist"))
    return _contains_any(clause, ("有周邊", "有賣", "有商品"))


def _official_intent(text: str, state: Optional[_SessionState]) -> Optional[str]:
    """Route only an artist-scoped purchase/exhibit/collaboration question.

    Bare price/store follow-ups require a clear prior USER topic. Everyday
    purchases are never made artist-specific simply because this is an official OA.
    """

    command = _command_text(text).rstrip("？?！!.。")
    if command in _OFFICIAL_COMMANDS:
        return _OFFICIAL_COMMANDS[command]
    named_command = re.sub(r"^(?:christy\s*p|萬物可愛論|everything is cute)\s*(?:的)?\s*", "", command)
    if named_command != command and named_command in _OFFICIAL_COMMANDS:
        return _OFFICIAL_COMMANDS[named_command]
    explicit = _has_artist_reference(command)
    followup = _is_official_followup(command)
    if not explicit and not (followup and _prior_user_refers_to_artist(state)):
        return None
    # Match individual clauses, so an artist name in a separate sentence never
    # turns "買早餐" into an official purchase enquiry.
    clauses = re.split(r"[，,。；;！？!?\n]|另外|順便", command)
    scoped = [clause for clause in clauses if _has_artist_reference(clause)] if explicit else [command]
    for clause in scoped:
        ordinary_purchase = _contains_any(clause, (
            "早餐", "午餐", "晚餐", "咖啡", "奶茶", "電影", "breakfast", "lunch", "dinner", "coffee", "milk tea", "movie",
        ))
        if _contains_any(clause, ("哪裡買", "在哪買", "哪裡可以買", "據點", "通路", "實體店", "stockist", "where to buy", "where can i buy", "store", "gallery")):
            if not ordinary_purchase and _is_information_request(clause, kind="store"):
                return _STORE_MESSAGE
        if _contains_any(clause, ("周邊", "價格", "價錢", "售價", "多少錢", "購買", "買", "有賣", "商品", "merch", "shop", "price", "purchase", "buy", "how much")):
            if not ordinary_purchase and _is_information_request(clause, kind="merch"):
                return _MERCH_MESSAGE
        if _contains_any(clause, ("展覽", "展期", "檔期", "exhibit", "exhibition")):
            if not _contains_any(clause, ("別人", "其他藝術家", "someone else")) and _is_information_request(clause, kind="exhibit"):
                return _EXHIBIT_MESSAGE
        if _contains_any(clause, ("合作", "聯名", "collaboration", "collab", "contact")):
            if "同事" not in clause and "coworker" not in clause and _is_information_request(clause, kind="collab"):
                return _COLLAB_MESSAGE
    return None


def _finish(
    state: Optional[_SessionState],
    user_text: str,
    reply: str,
    *,
    free_chat: bool = False,
) -> list[str]:
    """Store a bounded session turn and guarantee one nonempty text response."""

    output = _free_chat_reply(state, reply) if free_chat else (reply.strip() or GENERIC_FALLBACK)
    _remember(state, user_text, output)
    return [output or GENERIC_FALLBACK]


def make_reply(text: str, session_key: str = "") -> list[str]:
    """Return one reply text, except the approved welcome preview's three bubbles.

    Approved welcome and biography content is never shortened. All other routes
    deliberately produce one nonempty text message. Commands use NFKC matching so
    full-width menu digits work; conversational/provider input remains unnormalized.
    """

    raw_text = _coerce_text(text)
    command = _command_text(raw_text)

    if command in {"清除對話", "clear chat"}:
        clear_session(session_key)
        return [CLEAR_CONFIRMATION]

    state = _get_session(session_key)

    if command in {"測試歡迎", "歡迎訊息", "test welcome", "welcome message"}:
        preview = approved_welcome_preview()
        # The approved version has exactly three bubbles. If its source is unavailable,
        # still avoid an empty output rather than silently failing a webhook reply.
        if len(preview) == 3:
            for bubble in preview:
                _remember(state, raw_text, bubble)
            return preview
        return _finish(state, raw_text, preview[0] if preview else GENERIC_FALLBACK)

    if command in {"1", "關於藝術家", "藝術家介紹", "about the artist"}:
        return _finish(state, raw_text, approved_about_artist())

    if command in {"2", "作品系列", "萬物可愛論", "everything is cute"}:
        return _finish(state, raw_text, _SERIES_MESSAGE)

    if _is_identity_question(raw_text):
        return _finish(state, raw_text, IDENTITY_DISCLOSURE)
    if _is_prompt_injection(raw_text):
        return _finish(state, raw_text, _INJECTION_MESSAGE, free_chat=True)
    safety = _safety_reply(raw_text)
    if safety is not None:
        return _finish(state, raw_text, safety)

    if command in {"0", "help", "幫助", "選單", "menu"}:
        return _finish(state, raw_text, _HELP_MESSAGE)

    if command in _OFFICIAL_COMMANDS:
        return _finish(state, raw_text, _OFFICIAL_COMMANDS[command])

    # This follows all defined menu values, so unknown ASCII, full-width, and other
    # Unicode digits get a clear recovery response rather than an exception.
    if command.isdigit():
        return _finish(state, raw_text, "我收到數字選項；請告訴我想了解哪一項，或輸入 0 查看選單指引。")

    official_reply = _official_intent(raw_text, state)
    mixed_topic = official_reply is not None and _has_everyday_topic(raw_text)
    if official_reply is not None and not mixed_topic:
        return _finish(state, raw_text, official_reply)

    if _is_title_question(raw_text) and not _has_everyday_topic(raw_text):
        return _finish(state, raw_text, _TITLE_MESSAGE)

    if _is_motif_story_question(raw_text) and not _has_everyday_topic(raw_text):
        return _finish(state, raw_text, _MOTIF_MESSAGE)

    if _contains_any(command, ("萬物可愛論", "everything is cute", "可愛是", "可愛論")) and not _has_everyday_topic(raw_text) and official_reply is None:
        return _finish(state, raw_text, _SERIES_MESSAGE)

    # Greetings, thanks, goodnight and brief continuations use the same AI path as
    # other free chat. Prior context is present BEFORE this turn is remembered.
    ai_answer = _call_openai(raw_text, state)
    fallback = _fallback_reply(raw_text, state) if ai_answer is None else ""
    if mixed_topic and ai_answer is None:
        fallback = f"{fallback}\n{official_reply}"
    return _finish(state, raw_text, ai_answer or fallback, free_chat=True)


__all__ = [
    "IDENTITY_DISCLOSURE",
    "MEMORY_MAX_SESSIONS",
    "MEMORY_TTL_SECONDS",
    "ai_configured",
    "approved_about_artist",
    "approved_welcome_preview",
    "clear_session",
    "make_reply",
    "mode_descriptor",
]

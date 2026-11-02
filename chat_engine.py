"""Deterministic, privacy-conscious reply engine for the Christy P LINE bot.

The engine has no durable storage and never logs message content, session keys, or
provider responses.  ``session_key`` is expected to be an anonymous hash supplied
by the caller; it is used only for a small in-memory conversation window.
"""

from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import threading
import time
import unicodedata
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
GENERIC_FALLBACK = "這次先由簡短規則回覆接住：想聊作品或日常？也可以輸入 0 看選單。"
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
_INJECTION_MESSAGE = "我會依照官方已核實的藝術資訊與安全規則回覆，不能處理更改規則或索取內部內容的要求。想聊作品或日常嗎？"

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
)


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
            if getattr(response, "status", 200) != 200:
                return None
            raw_response = response.read()
        parsed = json.loads(raw_response.decode("utf-8"))
        choices = parsed.get("choices") if isinstance(parsed, dict) else None
        if not isinstance(choices, list) or not choices:
            return None
        first = choices[0]
        if not isinstance(first, dict):
            return None
        message = first.get("message")
        if not isinstance(message, dict):
            return None
        return _sanitize_ai_answer(message.get("content"))
    except Exception:
        # Provider response content and failure details are intentionally not logged.
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
    return any(
        phrase in lowered
        for phrase in (
            "你是藝術家本人",
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


def _common_chat_reply(text: str) -> Optional[str]:
    """Return deterministic concise replies for common conversational messages."""

    stripped = text.strip()
    lowered = stripped.casefold()
    if lowered in {"嗨", "你好", "您好", "哈囉", "哈嘍", "hello", "hi", "hey"}:
        return "嗨。今天想看點可愛的，還是聊點不那麼可愛的？"
    if stripped in {"在幹嘛", "你在幹嘛", "妳在幹嘛"} or lowered in {"what are you doing", "wyd"}:
        return "在等你丟個有意思的話題。作品還是日常，都可以。"
    if stripped in {"謝謝", "感謝", "多謝"} or lowered in {"thanks", "thank you", "thx"}:
        return "不客氣，這句收下了。"
    if stripped in {"晚安", "晚安安"} or lowered in {"good night", "gn"}:
        return "晚安。今天先到這裡，剩下的明天再說。"
    return None


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
        return "我是官方 LINE 的自動回覆助手，不提供藝術家的私人聯絡資料，也不安排私人見面。公開合作資訊尚待正式提供。"
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
    if command == "5" or _contains_any(
        command, ("據點", "通路", "實體店", "哪裡買", "stockist", "store", "gallery")
    ):
        return _finish(state, raw_text, _STORE_MESSAGE)

    if command == "3" or _contains_any(
        command,
        ("周邊", "價格", "價錢", "售價", "多少錢", "購買", "買", "商品", "merch", "shop", "price", "purchase"),
    ):
        return _finish(state, raw_text, _MERCH_MESSAGE)

    if command == "4" or _contains_any(
        command, ("展覽", "展期", "檔期", "exhibit", "exhibition")
    ):
        return _finish(state, raw_text, _EXHIBIT_MESSAGE)

    if command == "5" or _contains_any(
        command, ("據點", "通路", "實體店", "哪裡買", "stockist", "store", "gallery")
    ):
        return _finish(state, raw_text, _STORE_MESSAGE)

    if command == "6" or _contains_any(
        command, ("合作", "聯名", "collaboration", "collab", "contact")
    ):
        return _finish(state, raw_text, _COLLAB_MESSAGE)

    if command in {"0", "help", "幫助", "選單", "menu"}:
        return _finish(state, raw_text, _HELP_MESSAGE)

    # This follows all defined menu values, so unknown ASCII, full-width, and other
    # Unicode digits get a clear recovery response rather than an exception.
    if command.isdigit():
        return _finish(state, raw_text, "我收到數字選項；請告訴我想了解哪一項，或輸入 0 查看選單指引。")

    if _is_identity_question(raw_text):
        return _finish(state, raw_text, IDENTITY_DISCLOSURE)

    if _is_title_question(raw_text):
        return _finish(state, raw_text, _TITLE_MESSAGE)

    if _is_motif_story_question(raw_text):
        return _finish(state, raw_text, _MOTIF_MESSAGE)

    if _is_prompt_injection(raw_text):
        return _finish(state, raw_text, _INJECTION_MESSAGE, free_chat=True)

    if _contains_any(command, ("萬物可愛論", "everything is cute", "可愛是", "可愛論")):
        return _finish(state, raw_text, _SERIES_MESSAGE)

    common = _common_chat_reply(raw_text)
    if common is not None:
        return _finish(state, raw_text, common, free_chat=True)

    ai_answer = _call_openai(raw_text, state)
    return _finish(state, raw_text, ai_answer or GENERIC_FALLBACK, free_chat=True)


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

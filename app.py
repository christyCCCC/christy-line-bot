"""Christy P LINE webhook: native welcome, Chinese image gallery, and text chat.

Only approved artist/works gallery postbacks reply. The four pending menu
sections remain silent. This service
does not schedule, push, or broadcast messages.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path

from flask import Flask, abort, request
import chat_engine
import gallery_cards
import ticket_reply
import tour_registration

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
WELCOME_DELIVERY = os.environ.get("WELCOME_DELIVERY", "line_official_account")
TEXT_CHAT_ENABLED = os.environ.get("TEXT_CHAT_ENABLED", "true").lower() in {"1", "true", "yes"}
WELCOME_MESSAGE = Path(__file__).with_name("welcome_message_zh.txt").read_text(encoding="utf-8").strip()
WELCOME_IMAGE_VERSION = "cover_20261108"
WELCOME_IMAGE_URL = "https://christy-line-bot.onrender.com/static/gallery/welcome_cover_20261108.jpg"
ABOUT_ARTIST_MESSAGE = Path(__file__).with_name("about_artist_zh.txt").read_text(encoding="utf-8").strip()
ABOUT_ARTIST_POSTBACK = "christy_p:about"

# Only known event names are logged. Unknown values are normalized so event
# diagnostics never echo user-controlled fields or payload contents.
KNOWN_EVENT_TYPES = frozenset(
    {
        "follow",
        "unfollow",
        "join",
        "leave",
        "memberJoined",
        "memberLeft",
        "message",
        "postback",
        "beacon",
        "accountLink",
        "things",
        "unsend",
        "videoPlayComplete",
    }
)

if not CHANNEL_SECRET:
    raise RuntimeError("LINE_CHANNEL_SECRET is required for webhook verification")
if not CHANNEL_ACCESS_TOKEN:
    raise RuntimeError("LINE_CHANNEL_ACCESS_TOKEN is required for replies")
if WELCOME_DELIVERY not in {"line_official_account", "webhook"}:
    raise RuntimeError("WELCOME_DELIVERY must be line_official_account or webhook")
if not WELCOME_MESSAGE or len(WELCOME_MESSAGE) > 5000:
    raise RuntimeError("The approved Chinese welcome message is empty or too long")
if not ABOUT_ARTIST_MESSAGE or len(ABOUT_ARTIST_MESSAGE) > 5000:
    raise RuntimeError("The approved Chinese artist biography is empty or too long")


def reply_with_messages(reply_token: str, texts: list[str]) -> None:
    """Use LINE's one-time reply token once, with up to five text bubbles."""
    if not texts or len(texts) > 5 or any(not isinstance(t, str) or not t.strip() or len(t) > 5000 for t in texts):
        raise RuntimeError("Invalid outbound text messages")
    reply_with_message_objects(reply_token, [{"type": "text", "text": text} for text in texts])


def reply_with_message_objects(reply_token: str, messages: list[dict]) -> None:
    """Reply once with approved text/image objects; never push or broadcast."""
    if not messages or len(messages) > 5:
        raise RuntimeError("Invalid outbound message count")
    for message in messages:
        if not isinstance(message, dict):
            raise RuntimeError("Invalid outbound message")
        if message.get("type") == "text":
            text = message.get("text")
            if not isinstance(text, str) or not text.strip() or len(text.encode("utf-16-le")) // 2 > 5000:
                raise RuntimeError("Invalid outbound text")
        elif message.get("type") == "image":
            prefix = "https://christy-line-bot.onrender.com/static/gallery/"
            if any(not isinstance(message.get(key), str) or not message[key].startswith(prefix) for key in ("originalContentUrl", "previewImageUrl")):
                raise RuntimeError("Invalid outbound image URL")
        else:
            raise RuntimeError("Unsupported outbound message type")
    payload = {
        "replyToken": reply_token,
        "messages": messages,
    }
    outbound = urllib.request.Request(
        "https://api.line.me/v2/bot/message/reply",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(outbound, timeout=8) as response:
        if response.status != 200:
            raise RuntimeError(f"LINE reply API returned HTTP {response.status}")


def reply_with_text(reply_token: str, text: str) -> None:
    """Send one text bubble."""
    reply_with_messages(reply_token, [text])


def reply_to_follow(reply_token: str) -> None:
    """Send the original welcome cover first, then the complete approved Chinese copy."""
    reply_with_message_objects(reply_token, [
        {"type": "image", "originalContentUrl": WELCOME_IMAGE_URL, "previewImageUrl": WELCOME_IMAGE_URL},
        {"type": "text", "text": WELCOME_MESSAGE},
    ])


def reply_to_about_artist(reply_token: str) -> None:
    """Send artist images and the approved Chinese biography."""
    objects = gallery_cards.resolve_postback(ABOUT_ARTIST_POSTBACK)
    if objects:
        reply_with_message_objects(reply_token, objects)
    else:
        reply_with_text(reply_token, ABOUT_ARTIST_MESSAGE)


def anonymous_session_key(source: dict) -> str:
    """Create the same anonymous memory key for text and gallery postbacks."""
    user_id = source.get("userId", "")
    context_id = source.get("groupId") or source.get("roomId") or "private"
    raw_key = str(context_id) + ":" + str(user_id)
    return hmac.new(CHANNEL_SECRET.encode(), raw_key.encode(), hashlib.sha256).hexdigest() if user_id else ""


def reply_to_gallery(reply_token: str, objects: list[dict], session_key: str, request_text: str) -> None:
    logger.info("LINE gallery prepared: images=%s messages=%s", sum(message.get("type") == "image" for message in objects), len(objects))
    reply_with_message_objects(reply_token, objects)
    context = "\n\n".join(message["text"] for message in objects if message.get("type") == "text")
    chat_engine.remember_gallery_context(session_key, request_text, context)


def reply_to_text(reply_token: str, text: str, source: dict) -> None:
    """Use direct Chinese gallery routes first, then natural AI conversation."""
    session_key = anonymous_session_key(source)
    if chat_engine.is_welcome_request(text):
        reply_to_follow(reply_token)
        return
    private_chat = source.get("type") not in {"group", "room"} and not (source.get("groupId") or source.get("roomId"))
    tour_objects = tour_registration.resolve_text(text, session_key, private_chat=private_chat)
    if tour_objects:
        logger.info("LINE private tour reply prepared: messages=%s", len(tour_objects))
        reply_with_message_objects(reply_token, tour_objects)
        return
    ticket_objects = ticket_reply.resolve_text(text)
    if ticket_objects:
        logger.info("LINE ticket invitation prepared: images=1 messages=2")
        reply_with_message_objects(reply_token, ticket_objects)
        chat_engine.remember_ticket_context(session_key, text, ticket_reply.THANK_YOU_MESSAGE)
        return
    objects = gallery_cards.resolve_text(text, session_key)
    if objects:
        reply_to_gallery(reply_token, objects, session_key, text)
        return
    try:
        texts = chat_engine.make_reply(text, session_key)
    except Exception:
        logger.warning("LINE chat fallback: error_status=chat_unavailable")
        texts = ["這句我暫時沒接好，再說一點，我換個角度接。"]
    reply_with_messages(reply_token, texts)


def safe_event_type(event: dict) -> str:
    """Return a diagnostics-safe event type without exposing arbitrary input."""
    event_type = event.get("type")
    if isinstance(event_type, str) and event_type in KNOWN_EVENT_TYPES:
        return event_type
    return "other"


def send_event_reply(event: dict, event_type: str, reply_function) -> None:
    """Reply once, recording only event type and bounded error-status diagnostics."""
    reply_token = event.get("replyToken")
    if not isinstance(reply_token, str) or not reply_token:
        logger.warning(
            "LINE reply skipped: event_type=%s error_status=missing_reply_token",
            event_type,
        )
        return

    try:
        reply_function(reply_token)
        logger.info("LINE reply completed: event_type=%s error_status=ok", event_type)
    except urllib.error.HTTPError as exc:
        logger.error(
            "LINE reply failed: event_type=%s error_status=http_%s",
            event_type,
            exc.code,
        )
        abort(502)
    except (urllib.error.URLError, OSError):
        logger.error(
            "LINE reply failed: event_type=%s error_status=transport_error",
            event_type,
        )
        abort(502)
    except RuntimeError:
        logger.error(
            "LINE reply failed: event_type=%s error_status=reply_api_error",
            event_type,
        )
        abort(502)


@app.post("/callback")
def callback():
    """Validate LINE's signature and reply only to approved event actions."""
    body = request.get_data()
    supplied = request.headers.get("X-Line-Signature", "")
    expected = base64.b64encode(
        hmac.new(CHANNEL_SECRET.encode("utf-8"), body, hashlib.sha256).digest()
    ).decode("ascii")
    if not hmac.compare_digest(supplied, expected):
        logger.warning("LINE webhook rejected: error_status=invalid_signature")
        abort(400)

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        logger.warning("LINE webhook rejected: error_status=invalid_payload")
        abort(400)

    for event in payload["events"]:
        if not isinstance(event, dict):
            logger.warning("LINE webhook ignored: event_type=invalid error_status=malformed_event")
            continue

        event_type = safe_event_type(event)
        logger.info("LINE webhook received: event_type=%s", event_type)

        if event_type == "follow" and WELCOME_DELIVERY == "webhook":
            send_event_reply(event, event_type, reply_to_follow)
            continue

        if event_type == "message" and TEXT_CHAT_ENABLED:
            message = event.get("message")
            if isinstance(message, dict) and message.get("type") == "text" and isinstance(message.get("text"), str):
                source = event.get("source")
                if not isinstance(source, dict):
                    source = {}
                send_event_reply(event, event_type, lambda token: reply_to_text(token, message["text"], source))
            continue

        if event_type != "postback":
            continue

        postback = event.get("postback")
        if not isinstance(postback, dict) or not isinstance(postback.get("data"), str):
            continue
        source = event.get("source")
        session_key = anonymous_session_key(source if isinstance(source, dict) else {})
        objects = gallery_cards.resolve_postback(postback["data"], session_key)
        if objects:
            send_event_reply(event, event_type, lambda token: reply_to_gallery(token, objects, session_key, postback["data"]))

    return "OK", 200


@app.get("/health")
def health():
    return "OK", 200


@app.get("/status")
def status():
    return {
        "brand": "Christy P",
        "mode": (
            ("native_welcome_about_and_chat" if TEXT_CHAT_ENABLED else "native_welcome_and_about")
            if WELCOME_DELIVERY == "line_official_account"
            else ("webhook_welcome_about_and_chat" if TEXT_CHAT_ENABLED else "webhook_welcome_and_about")
        ),
        "greeting_enabled": True,
        "welcome_delivery": WELCOME_DELIVERY,
        "about_artist_enabled": True,
        "ordinary_messages_enabled": TEXT_CHAT_ENABLED,
        "chat_mode": ("ai_with_rules" if chat_engine.ai_configured() else "rules_only") if TEXT_CHAT_ENABLED else "off",
        "ai_configured": chat_engine.ai_configured(),
        "chat_style": "responsive_low_questions_v3",
        "gallery_trigger_version": "natural_requests_v2",
        "welcome_test_command": "測試歡迎" if TEXT_CHAT_ENABLED else None,
        "welcome_image_version": WELCOME_IMAGE_VERSION,
        "ticket_reply_version": ticket_reply.VERSION,
        "ticket_reply_enabled": TEXT_CHAT_ENABLED,
        "tour_registration_version": tour_registration.VERSION,
        "tour_registration_enabled": TEXT_CHAT_ENABLED,
        "scheduled_broadcast": False,
        **gallery_cards.content_status(),
    }, 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))

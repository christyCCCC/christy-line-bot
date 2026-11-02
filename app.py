"""Christy P LINE webhook: follow greeting and approved artist biography.

All ordinary messages and every postback other than ``christy_p:about`` remain
silent. This service does not schedule, push, broadcast, or provide AI chat.
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

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
WELCOME_DELIVERY = os.environ.get("WELCOME_DELIVERY", "line_official_account")
WELCOME_MESSAGE = Path(__file__).with_name("welcome_message.txt").read_text(encoding="utf-8").strip()
ABOUT_ARTIST_MESSAGE = Path(__file__).with_name("about_artist.txt").read_text(encoding="utf-8").strip()
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
    raise RuntimeError("The approved bilingual welcome message is empty or too long")
if not ABOUT_ARTIST_MESSAGE or len(ABOUT_ARTIST_MESSAGE) > 5000:
    raise RuntimeError("The approved bilingual artist biography is empty or too long")


def reply_with_text(reply_token: str, text: str) -> None:
    """Send one approved text message using LINE's one-time reply token."""
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text}],
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


def reply_to_follow(reply_token: str) -> None:
    """Send the approved welcome message for a follow event."""
    reply_with_text(reply_token, WELCOME_MESSAGE)


def reply_to_about_artist(reply_token: str) -> None:
    """Send the approved bilingual artist biography for its exact postback."""
    reply_with_text(reply_token, ABOUT_ARTIST_MESSAGE)


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

        if event_type != "postback":
            continue

        postback = event.get("postback")
        if isinstance(postback, dict) and postback.get("data") == ABOUT_ARTIST_POSTBACK:
            send_event_reply(event, event_type, reply_to_about_artist)

    return "OK", 200


@app.get("/health")
def health():
    return "OK", 200


@app.get("/status")
def status():
    return {
        "brand": "Christy P",
        "mode": (
            "native_welcome_and_about"
            if WELCOME_DELIVERY == "line_official_account"
            else "webhook_welcome_and_about"
        ),
        "greeting_enabled": True,
        "welcome_delivery": WELCOME_DELIVERY,
        "about_artist_enabled": True,
        "ordinary_messages_enabled": False,
        "scheduled_broadcast": False,
    }, 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))

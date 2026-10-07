"""Christy P LINE webhook: bilingual greeting on follow only.

All ordinary messages and rich-menu postbacks remain silent. This service does
not schedule, push, or broadcast messages.
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
WELCOME_MESSAGE = Path(__file__).with_name("welcome_message.txt").read_text(encoding="utf-8").strip()
if not CHANNEL_SECRET:
    raise RuntimeError("LINE_CHANNEL_SECRET is required for webhook verification")
if not CHANNEL_ACCESS_TOKEN:
    raise RuntimeError("LINE_CHANNEL_ACCESS_TOKEN is required for the welcome reply")
if not WELCOME_MESSAGE or len(WELCOME_MESSAGE) > 5000:
    raise RuntimeError("The approved bilingual welcome message is empty or too long")


def reply_to_follow(reply_token: str) -> None:
    """Send one approved text message using LINE's one-time reply token."""
    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": WELCOME_MESSAGE}],
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


@app.post("/callback")
def callback():
    """Validate LINE's signature; respond only to a follow event."""
    body = request.get_data()
    supplied = request.headers.get("X-Line-Signature", "")
    expected = base64.b64encode(
        hmac.new(CHANNEL_SECRET.encode("utf-8"), body, hashlib.sha256).digest()
    ).decode("ascii")
    if not hmac.compare_digest(supplied, expected):
        abort(400)

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        abort(400)

    for event in payload["events"]:
        if not isinstance(event, dict) or event.get("type") != "follow":
            continue
        reply_token = event.get("replyToken")
        if not isinstance(reply_token, str) or not reply_token:
            logger.warning("Follow event without a reply token; no welcome sent")
            continue
        try:
            reply_to_follow(reply_token)
            logger.info("Christy P bilingual welcome sent for follow event")
        except urllib.error.HTTPError as exc:
            logger.error("LINE welcome reply rejected: HTTP %s", exc.code)
            abort(502)
        except (urllib.error.URLError, OSError, RuntimeError) as exc:
            logger.error("LINE welcome reply failed: %s", type(exc).__name__)
            abort(502)
    return "OK", 200


@app.get("/health")
def health():
    return "OK", 200


@app.get("/status")
def status():
    return {
        "brand": "Christy P",
        "mode": "welcome_only",
        "greeting_enabled": True,
        "ordinary_messages_enabled": False,
        "scheduled_broadcast": False,
    }, 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))

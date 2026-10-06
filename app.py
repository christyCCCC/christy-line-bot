"""Christy P official LINE account: silent transition mode.

This temporary service keeps LINE's webhook endpoint available while the new
artwork, merchandise, exhibition and store content is being prepared. It does
not send or schedule any messages.
"""

import base64
import hashlib
import hmac
import logging
import os

from flask import Flask, abort, request

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
if not CHANNEL_SECRET:
    raise RuntimeError("LINE_CHANNEL_SECRET is required for webhook verification")


@app.post("/callback")
def callback():
    """Verify LINE signature, acknowledge event and intentionally remain silent."""
    body = request.get_data()
    supplied = request.headers.get("X-Line-Signature", "")
    expected = base64.b64encode(
        hmac.new(CHANNEL_SECRET.encode("utf-8"), body, hashlib.sha256).digest()
    ).decode("ascii")
    if not hmac.compare_digest(supplied, expected):
        abort(400)
    logger.info("LINE webhook acknowledged without sending a reply")
    return "OK", 200


@app.get("/health")
def health():
    return "OK", 200


@app.get("/status")
def status():
    return {"brand": "Christy P", "mode": "silent", "scheduled_broadcast": False}, 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))

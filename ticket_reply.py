"""Approved exhibition invitation replies, without AI, pushes, or broadcasts."""
import re
import unicodedata

VERSION = "yak_invitation_20261110"
IMAGE_URL = "https://christy-line-bot.onrender.com/static/gallery/yak_invitation_20261110.jpg"
THANK_YOU_MESSAGE = (
    "這張是高雄漾藝術博覽會的邀請函，先收好。\n\n"
    "憑這張邀請函，可以再帶一位朋友一起入場喔。\n"
    "入場時請依邀請函上的說明與現場規定使用。\n\n"
    "謝謝你願意走進我的藝術世界，期待在展場見到你。"
)
KEYWORDS = (
    "門票", "门票", "索票", "贈票", "赠票", "領票", "领票", "取票", "票券",
    "入場券", "入场券", "邀請函", "邀请函", "電子票", "电子票",
    "購票", "购票", "買票", "买票", "售票", "票價", "票价", "免費票", "免费票",
    "想要票", "我要票", "給我票", "给我票", "送我票", "一張票", "一张票",
    "兩張票", "两张票", "入場", "入场", "索取票", "索取邀請", "索取邀请",
    "拿票", "送票", "要票", "有票", "求票", "票怎麼", "票怎么", "票在哪",
    "票哪裡", "票哪里", "邀請卡", "邀请卡",
)
_ENGLISH = re.compile(r"\b(?:tickets?|admission(?:\s+(?:ticket|pass))?|entry\s+pass(?:es)?|invitation(?:\s+(?:card|letter))?)\b", re.IGNORECASE)


def resolve_text(text: str) -> list[dict] | None:
    """Match ticket-related text broadly, without matching unrelated words like 股票."""
    if not isinstance(text, str):
        return None
    normalized = unicodedata.normalize("NFKC", text).strip().casefold()
    compact = re.sub(r"\s+", "", normalized)
    if not (re.fullmatch(r"票[?!！？。.!]*", compact) or any(word in compact for word in KEYWORDS) or _ENGLISH.search(normalized)):
        return None
    return [
        {"type": "image", "originalContentUrl": IMAGE_URL, "previewImageUrl": IMAGE_URL},
        {"type": "text", "text": THANK_YOU_MESSAGE},
    ]

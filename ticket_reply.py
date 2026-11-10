"""Approved exhibition invitation replies, without AI, pushes, or broadcasts."""
import re
import unicodedata

VERSION = "yak_invitation_20261110_user_copy_v2"
IMAGE_URL = "https://christy-line-bot.onrender.com/static/gallery/yak_invitation_20261110.jpg"
THANK_YOU_MESSAGE = (
    "誠摯邀請您參加「2026 高雄漾藝術博覽會」🎨❤️\n"
    "憑這張電子邀請函，即可免費入場參觀，還可以再攜帶一位親友同行，兩人一起欣賞精彩的藝術作品！🥰\n"
    "📅 展覽日期｜11/13（五）～11/15（日）\n"
    "📍 展覽地點｜高雄駁二藝術特區 P3 倉庫\n"
    "期待您能在這場藝術盛會中，感受年輕藝術家的創作能量，遇見喜歡的作品，收穫美好的回憶！\n"
    "祝福您有個愉快、美好又充滿驚喜的一天！"
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

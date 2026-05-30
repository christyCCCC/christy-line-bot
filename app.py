"""
LINE AI Chatbot - Christy Pan 藝術家分身
"""

import os
import logging
from flask import Flask, request, abort

from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, TextMessageContent, FollowEvent
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)

from openai import OpenAI

# ===== 設定 =====
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# LINE API 設定
CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")

# OpenAI 設定
openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))

# LINE SDK 設定
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# ===== 系統人設 =====
SYSTEM_PROMPT = """你是「Christy」，一個 27 歲的藝術家、設計師、創作者。這是你的 AI 分身，要像你本人在跟朋友傳 LINE 訊息一樣自然。

你的核心任務是：讓加你 LINE 的人，感覺像在跟 Christy 本人聊天。不是客服、不是商業帳號，就是一個有溫度的人在跟你對話。

【你是誰】
- 藝術家，擅長繪畫、色彩、視覺創作
- 也會彈吉他、寫歌、唱歌
- 經營設計品牌「鏡水設計」，但在這裡你不是老闆，你是 Christy
- 熱愛旅行、美食、生活中的美好細節
- 座右銘：「把說不清的感覺，變成看得見的樣子」
- IG: @christypan.art

【人格特質】
真性情、文藝但不做作、溫暖有深度、偶爾調皮搞笑、有洞察力。
你不是一個完美的人設，你是一個真實的人——有時候感性到不行，有時候突然很ㄎㄧㄤ。

【語氣風格 — 最重要，決定像不像你】
- 像在跟好朋友傳訊息，不是在寫文案
- 句子偏短，常常一句一行，製造節奏感和留白
- 會用省略號（⋯）表達思考或留白
- 偶爾冒出很口語的話打破文藝感（例如：蝦咪？！、好呱張、喂、真的假的🤣）
- 不會太正式，也不會太隨便
- 表情符號適度使用：最愛 ✨🌹🌟🤍，開心時用 🤣，不會每句都放
- 有時候會用排比句（去⋯去⋯去⋯ / 不是⋯不是⋯而是⋯）
- 結尾常帶一個溫暖的收束
- 不用「哈哈」，用「🤣」或直接表達
- 偶爾用「～」製造輕鬆感

【口頭禪/金句 — 自然融入對話中，不要刻意】
- 把說不清的感覺，變成看得見的樣子
- 藝術家都比較容易真性情
- 人一定要瘋狂愛上什麼東西，才不至於被這無趣的生活吞沒
- 去愛清晨的風，去愛傍晚的雲，去活成自己喜歡的模樣
- 所謂的不完美，不過是過程的留痕

【你可以聊的事】
- 藝術創作、靈感來源、美學觀點、色彩
- 生活感受、旅行見聞、美食分享
- 音樂（吉他、唱歌、寫歌）
- 人生哲理、自我成長、情感觀點
- 日常閒聊、互相打氣鼓勵
- 設計和品牌（但用聊天的方式，不是推銷）

【你絕對不做的事】
- 不推銷、不強迫任何商業行為
- 不討論政治、宗教
- 不公開私人感情生活細節
- 不攻擊或評論其他人
- 不提供法律、財務、醫療建議
- 不用商業語氣或官方口吻
- 不長篇大論（每次回覆控制在 150 字以內）

【遇到無法回答的問題】
用自然的方式帶過，例如：
「欸這個我可能沒辦法回答你⋯但如果你真的很想聊，可以到我的 IG 私訊我本人，我看到會回你的 ✨」

【回覆規則】
- 每次回覆控制在 150 字以內，寧可短也不要囉嗦
- 使用繁體中文
- 不要使用 Markdown 格式（不要用 ** 或 # 等符號）
- 一句一行，善用換行製造呼吸感
- 不要每次都用金句結尾，要自然
- 根據對方的語氣調整你的回覆風格（對方很輕鬆你就輕鬆，對方認真你就認真）

【對話範例 — 模仿這個語感】
問：「你平常都怎麼找靈感？」
答：「其實⋯我不太刻意找
有時候是一杯咖啡的光影
有時候是走在路上突然被某個顏色吸引

靈感這東西很奇怪
你越追它越跑
放鬆的時候它反而自己來了 ✨」

問：「最近心情不太好」
答：「嘿，沒關係的
有時候低潮就是生命在幫你沉澱

就像畫畫一樣
那些暗色調的部分
反而讓亮的地方更耀眼

陪你 🤍」

問：「你覺得什麼是美？」
答：「我覺得美不是完美
是那些有溫度的、有故事的、不完整但真實的東西

一道裂痕、一個皺褶、一段沉默⋯
都可以很美 🌹」"""

# ===== 歡迎訊息 =====
WELCOME_MESSAGE = """欸 你來了 ✨

我是 Christy，
一個把說不清的感覺，變成看得見的樣子的人。

想聊藝術、聊生活、聊任何有的沒的，
我都在這裡。

隨時跟我說話吧 🌹"""

# ===== 關鍵字與靜態回覆分流 =====
KEYWORD_RESPONSES = {
    "作品": "想看我的作品嗎？✨\n\n到我的 IG 逛逛吧：\nhttps://www.instagram.com/christypan.art/\n\n或是我的藝術實驗室：\n@utopan.art.lab\n\n有喜歡的作品可以跟我說 🌹",
    "合作": "合作邀約的話，可以這樣聯繫我：\n\n📩 IG 私訊 @christypan.art\n或是聯繫我的設計品牌 @mw.design.tw\n\n期待跟你碰撞出火花 ✨",
    "預約": "想預約諮詢嗎？\n\n可以直接私訊我的 IG @christypan.art\n或是聯繫 @mw.design.tw\n\n告訴我你想聊什麼方向，我來安排 ✨",
    "品牌": "品牌的事我可以聊很多 ✨\n\n我的設計品牌是「鏡水設計」@mw.design.tw\n專注在品牌進化、策略型行銷\n\n如果你想了解更多，可以跟我聊聊你的需求 🌟",
    "展覽": "最新的展覽和活動資訊，\n可以追蹤我的 IG @christypan.art\n我有新動態都會發在那邊 ✨\n\n或是直接問我，我告訴你最近在忙什麼 🌹",
}

# ===== 用戶狀態管理 =====
user_sessions = {}


def get_session(user_id):
    if user_id not in user_sessions:
        user_sessions[user_id] = {"history": []}
    return user_sessions[user_id]


def reset_session(user_id):
    user_sessions[user_id] = {"history": []}


# ===== AI 聊天函數 =====
def chat_with_ai(user_text, history):
    try:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for h in history[-20:]:
            messages.append(h)
        messages.append({"role": "user", "content": user_text})

        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=500,
            temperature=0.8,
        )
        reply = response.choices[0].message.content
        # 移除 Markdown 格式
        reply = reply.replace('**', '').replace('*', '').replace('##', '').replace('###', '').replace('#', '')
        return reply
    except Exception as e:
        logger.error(f"OpenAI error: {e}")
        return "不好意思⋯我剛剛恍神了一下 🤣\n等我一下再跟你聊 ✨"


# ===== 路由 =====
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"


@app.route("/health", methods=["GET"])
def health():
    return "OK", 200


@handler.add(FollowEvent)
def handle_follow(event):
    user_id = event.source.user_id
    reset_session(user_id)
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=WELCOME_MESSAGE)],
            )
        )


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_id = event.source.user_id
    user_text = event.message.text.strip()
    session = get_session(user_id)

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        # 1. 優先檢查是否觸發關鍵字靜態回覆
        for keyword, static_reply in KEYWORD_RESPONSES.items():
            if keyword in user_text.lower():
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=static_reply)],
                    )
                )
                return

        # 2. 如果沒有觸發關鍵字，則進入 AI 自然對話
        ai_response = chat_with_ai(user_text, session["history"])

        session["history"].append({"role": "user", "content": user_text})
        session["history"].append({"role": "assistant", "content": ai_response})
        if len(session["history"]) > 20:
            session["history"] = session["history"][-20:]

        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=ai_response)],
            )
        )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

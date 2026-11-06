# Christy P 官方 LINE：文字聊天測試版

本版本開啟普通文字自動回覆，保留 LINE 原生雙語歡迎訊息與「認識 IP／官網」藝術家介紹。其餘五格 postback、貼圖／圖片／影片／音訊等非文字訊息仍不自動回覆。沒有每日廣播、排程、push、個資蒐集或舊品牌邏輯。

## 回應規則

每則有效的 LINE 文字事件（須有可用 reply token）都會進入回覆流程，包括純數字、符號、短句。LINE reply API 一個 token 只呼叫一次；通常一個文字框，只有歡迎预覽依原生後台限制分成三框。網路、LINE API 或 Render 休眠等外部條件仍可能導致送達失敗，不能把「已啟用」視為每則訊息實際已送達。

- `0`、`help`、`幫助`、`選單`：文字功能指南。
- `1`、`關於藝術家`、`藝術家介紹`：`about_artist.txt` 的核准全文。
- `2`、`作品系列`、`萬物可愛論`：核心系列介紹，不憑作品標題杜撰故事。
- `3`、`4`、`5`、`6`：分別說明周邊、公開展覽日期、購買據點、合作資料尚未提供／公告；不編造價格、日期、網址、Email 或表單。
- 其他數字：詢問查詢意圖並提示輸入 `0`。
- `測試歡迎`、`歡迎訊息`、`test welcome`、`welcome message`：只回傳給當前提問者，不是廣播。使用 `welcome_message.txt` 的核准全文，按中文及英文段落分為 255、318、376 字元三框，字句不刪改。
- `清除對話`：僅清除本助手的短暫上下文，不代表刪除 LINE 或模型供應商紀錄。

日常風格簡短、自然、輕柔親暱；先接住對方話題，偶爾使用非露骨的土味情話、幽默或押韻，不每句硬撩、不一直問「作品還是日常」或導回選單。使用者指定「好累」→「需要幫你捶捶背嗎？」作為接話基準，後續「好啊」「不用」根據上一句接話。聊天想像不等於實際到場或私人約見。對方拒絕就收回；重要情緒不拿來硬搞笑。

普通招呼與短續句優先交給 AI 讀最近的匿名上下文；無法使用 AI 才用主題相關的簡短備援，不假裝完整理解。日常「買早餐」「同事不合作」不應觸發商品／合作制式回覆。明確官方資訊與文字指令才保留確定性路由；仍不得杜撰價格、展覽、據點、聯絡方式。

日常開場不主動自我介紹，也不加「不是藝術家本人」等身分免責句；直接詢問身分才簡短誠實說明自動回覆角色。不冒充本人、不提供私人聯絡方式、不建客戶個資檔案，不恢復舊曖昧蒐集個資模式。「可愛」是觀看方式，理解不等於合理化傷害。

## AI 與備援

`chat_engine.py` 先處理確定性指令與已核准資訊，其他日常文字才使用 AI。`system_prompt.txt` 是新品牌專用規則。沿用既有 Bot 的使用者自備 OpenAI 環境設定，預設模型 `gpt-4o-mini`；不得將 Manus Sandbox 的內建代理憑證或 `OPENAI_API_BASE` 複製到 Render。本程式只讀服務自己的 `OPENAI_API_KEY` 與選用 `OPENAI_BASE_URL`，後者預設官方 `https://api.openai.com/v1`。

AI 呼叫有短超時與固定輸出上限，沒有工具或自動外部行動；失效／未設定時仍使用規則備援。`GET /status` 的 `ai_configured` 僅表示服務已配置 API key，並非成功模型回應或實際送達證明。聊天上下文只限服務記憶體中的匿名 session 雜湊，數量與時間有界；重啟後清空，不另存聊天內容或客户資料庫。

## 設定與部署

必需 `LINE_CHANNEL_SECRET`、`LINE_CHANNEL_ACCESS_TOKEN`。`TEXT_CHAT_ENABLED=true` 開啟文字；`AI_CHAT_ENABLED` 控制 AI；`WELCOME_DELIVERY=line_official_account` 為預設，FollowEvent 只驗簽後 ACK，不再次送歡迎。只有明確設 `WELCOME_DELIVERY=webhook` 才使用封存文字作程式歡迎 fallback。

LINE 後台保持聊天 ON、歡迎訊息 ON、Webhook ON、回應時間 OFF、普通原生自動回應 OFF／手動聊天模式，以免舊原生回覆干擾。其他五格按鈕仍保持靜默；文字指令開放不等於這五格已開放。

Render 服務 `srv-d8d8p1uk1jcs738o1vh0` 使用現有部署平台，autoDeploy 為 no，推送 GitHub 後必須手動 trigger deploy，核對 deployment live 與 `/status`。不要從舊 Git commits 部署舊品牌。正式 URL：`https://christy-line-bot.onrender.com`；Webhook `/callback`、健康 `/health`、狀態 `/status`。

測試：`AI_CHAT_ENABLED=false python -m unittest -v`，禁止單元測試使用真實 LINE 或 AI 憑證。診斷只記錄事件類型及有限錯誤狀態，不記錄使用者 ID、訊息、reply token、API key 或原始 provider response。

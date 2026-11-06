# Christy P 官方 LINE：雙語圖文導覽與自然聊天

本版本開啟藝術家與作品系列兩格的圖文導覽，保留 LINE 原生雙語歡迎訊息及普通文字聊天。周邊新品、展覽與檔期、購買據點、合作洽詢四格的 postback 仍靜默。貼圖、圖片、影片、音訊等使用者傳入的非文字訊息仍不自動回覆。沒有每日廣播、排程、push、個資蒐集或舊品牌邏輯。

## 圖文導覽

`gallery_cards.py` 優先解析已核准的藝術家／作品請求，不必等待 AI 現場生成完整介紹。回覆使用 LINE 原生 image 與 text message，一個 reply token 呼叫一次，每次至多五則訊息；最後一則文字附 quickReply postback 閱讀按鈕，不在聊天裡額外插入操作指令。

資料：`artist_cards.json`（七張）、`artworks_catalog.json`（第1–10件作品）。圖檔為使用者提供的原圖副本，保存在 `static/gallery/`，公開來源是現有正式服務的 HTTPS 路徑；未裁切、改字或生成替代圖。兩張缺少的第11、12件不編造。

- 「想了解藝術家」「藝術家介紹」或 `1`：封面、她是誰圖片，以及未刪改的 `about_artist.txt` 全文，附成長故事按鈕。
- 「作品介紹」「作品系列」「想看作品」或 `2`：系列圖片、詳細中英文介紹、十件目錄與作品選擇按鈕。
- 「作品1」「介紹第3件作品」「介紹愛會咬人」等：單件圖片、原句與詳細中英文導讀。
- postback `christy_p:about`、`christy_p:artworks`：前述兩個入口。
- postback `christy_p:artist:<key>`、`christy_p:work:<id>`：限定有效圖庫項目；未知值靜默。
- 「下一件」「上一件」「繼續」只有圖庫上下文有效時續讀。普通日常話題或拒絕、清除對話，退出圖庫模式；不把「我十三歲」當藝術家傳記，不把日常「讓我安靜一下／LEAVE ME ALONE」当看作品指令。

原句與「作品導讀／Reading」分開。導讀是基於使用者提供的主題及可見元素的閱讀角度，不冒充藝術家逐字聲明，不補造年份、尺寸、媒材、價格、展覽或其他傳記。每次正式藝術家、作品介紹都含繁體中文與英文；普通聊天仍以自然短句為主。

## 歡迎与其他文字指令

`WELCOME_DELIVERY=line_official_account`：真正 FollowEvent 只驗簽後 ACK，不重複送程式歡迎。原生歡迎內容不變，既有好友不補發。

「測試歡迎」「歡迎訊息」「test welcome」「welcome message」只回覆當前提問者，按已核准全文分成三框，不是廣播。

`0`、`help`、`幫助`、`選單`為文字功能指南。`3`、`4`、`5`、`6`仍說明周邊、公開展覽日期、購買據點、合作资料尚未提供，不虛構網址、Email或價格。要選單件作品請加「作品／第幾件」，不混淆普通功能數字。

「清除對話」清除本助手有限的匿名聊天與圖庫上下文，不代表刪除 LINE 或模型供應商的紀錄。

## 聊天規則

日常風格先接住對方，輕柔親暱，偶爾幽默、押韻或非露骨土味情話，不一直拉回選單。「好累」以「需要幫你捶捶背嗎？」為接話基準；「好啊」「不用」沿上一句走。尊重拒絕，不冒充實際到場或私人戀人，不蒐集個資，不拿重要情緒硬搞笑。

普通招呼與短續句優先交給 AI 讀近期匿名上下文；AI 不可用時採主題相關備援。日常買早餐、同事不合作不誤導至周邊／合作。身分只有直接問才誠實說明，不主動插入「不是藝術家本人」前言。理解不等於合理化傷害。

已成功送出的圖卡文字會進入同樣有限的匿名聊天上下文，供下一句問畫面細節使用，不儲存原始 LINE user ID、不建立客戶資料庫。記憶只在程序中，重啟會清空；postback 按鈕自身攜帶已知項目，可直接重開。

## AI、安全與部署

沿用服務自己的 `OPENAI_API_KEY`，選用 `OPENAI_BASE_URL`（預設官方網址）與 `OPENAI_MODEL`。不把 Manus Sandbox 內建代理憑證部署至 Render，不讀舊 `OPENAI_API_BASE`。AI 及 LINE API 有短逾時，仍不能把設定開啟當成每則已實際送達。

必需 `LINE_CHANNEL_SECRET` 與 `LINE_CHANNEL_ACCESS_TOKEN`。`TEXT_CHAT_ENABLED=true` 開啟文字；`AI_CHAT_ENABLED` 控制 AI。`WELCOME_DELIVERY=webhook` 僅為明確設定的程式歡迎備援，不與原生歡迎同時使用。

LINE 後台保留歡迎 ON、Webhook ON、普通原生自動回應 OFF、回應時間 OFF，避免舊自動回覆干擾。

Render 服務 `srv-d8d8p1uk1jcs738o1vh0`，autoDeploy=no，推送 GitHub 後須手動 trigger deploy，確認 deployment live 與 `/status.cards_version`。正式網址 `https://christy-line-bot.onrender.com`；Webhook `/callback`、健康 `/health`、狀態 `/status`。

本次不升級付費主機，也未處理免費主機冷啟動、持久補發或完整非同步訊息佇列。圖庫直接回覆可省去完整介紹的 AI 等待，不能消除 Render free 閒置後的喚醒延遲。

## 驗證

`AI_CHAT_ENABLED=false python3 -m unittest -v`。測試僅使用假 LINE 憑證及 mock 外送；不得用真實用戶做單元測試或廣播。正式檢查先核對 `@844tneii`，只做訊息物件 validate、圖片 HTTPS 回應、官方 Webhook test 及沒有 reply token 的事件驗證；手機實際收圖仍要另行實測。

日誌只記錄事件類型、有限 AI／LINE 錯誤類別，不記使用者內容、ID、reply token、API key 或供應商原始回應。

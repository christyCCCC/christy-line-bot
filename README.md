# Christy P 官方 LINE：中文圖文導覽與自然聊天

藝術家與作品系列兩格的介紹只顯示繁體中文，保留圖片、詳細導讀、自然文字觸發與快速閱讀按鈕。周邊新品、展覽與檔期、購買據點、合作洽詢四格的 postback 仍靜默。沒有每日廣播、push、排程或個資蒐集。

## 內容與來源

- `artist_cards.json`：七張藝術家圖卡，顯示 `text_zh`。
- `artworks_catalog.json`：第1–10件作品，顯示中文名稱、原句與完整 `reading_zh`。
- `about_artist_zh.txt`：核准中文藝術家簡介。
- `welcome_message_zh.txt`：核准中文歡迎顯示稿與測試預覽。
- `about_artist.txt`、`welcome_message.txt`及JSON英文欄位：原始雙語資料保留，不作現行文字輸出。
- `static/gallery/`：使用者原圖副本，不改圖、不裁切；原圖上已印有英文仍保留。

## 觸發

「作品」「畫作」「作品集」「作品介紹」「作品系列」或2：系列圖片、中文詳細概念、十件目錄及按鈕。

「你幫我介紹一張畫作」「可以介紹一幅作品嗎」：先提供第1件原圖、中文原句與導讀，不由普通AI臨時編寫。

「作品1」「介紹第3件作品」「介紹愛會咬人」：指定作品圖文。

「想了解藝術家」「你可以幫我介紹一下藝術家嗎」或1：介紹图片與完整中文簡介。

原有 `christy_p:about`、`christy_p:artworks`、允許的 `christy_p:artist:<key>`、`christy_p:work:<id>` postback 不變；未知或未開放選單靜默。閱讀中「上一件」「下一件」「繼續」沿導覽走；拒絕或改聊日常時退出，不把一般提及作品的敘述當指令。

## 歡迎來源

`WELCOME_DELIVERY=line_official_account` 時真正 FollowEvent 只驗簽後ACK，不重複發送程式歡迎。原生加入好友歡迎由 LINE Manager 管理，與本專案文案檔獨立；目前中文稿已準備，仍需登入後台刪除英文訊息框。未保存原生設定前，不可宣稱加入好友歡迎已更新。

「測試歡迎」「歡迎訊息」直接回核准中文稿一則，不是廣播、不補發既有好友。`WELCOME_DELIVERY=webhook` 僅是明確設定的程式歡迎備援，不應與原生歡迎並用。

## 安全及可靠性

一次 reply token 只呼叫一次回覆API，每次至多五則圖片或文字訊息；最後一則附quickReply。只允許固定圖庫HTTPS圖片路徑，不產生任意網址。

未知售價、展覽、據點、合作窗口仍明說尚無公開資訊。不恢復旧品牌、不冒充本人、不把关心包裝為個資蒐集。

匿名上下文只暫存記憶體，可清除，不代表刪除LINE或模型供應商紀錄。日誌僅記錄事件型別、圖片數與錯誤狀態，不記憑證或聊天正文。

## 維護

`AI_CHAT_ENABLED=false python3 -m unittest -v` 執行本地無發送測試。Render服務自動部署停用，推送Git後需手動部署，再核對`/status`的`cards_version=artist_works_zh_v2`、`content_language=zh-TW`與指定部署live狀態。不要只推送後宣稱上線。

使用既有Render免費主機；閒置喚醒延遲未因本次文字調整而消除。

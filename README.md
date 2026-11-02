# Christy P 官方 LINE：原生歡迎與藝術家介紹版

本版本保留簽章驗證的 LINE Webhook，**僅會對 `christy_p:about` postback 以 LINE reply API 回覆經核准的中英文藝術家介紹**；文案位於 `about_artist.txt`。這份檔案保留核准內容的原始段落順序，僅移除了 Markdown 標題前綴。一般文字、貼圖、未知 postback，以及其餘五格選單 postback 均維持靜默；沒有 AI 聊天、排程、廣播或 push 訊息。

預設 `WELCOME_DELIVERY=line_official_account`。因此 FollowEvent 僅會由 webhook 驗簽並回 `200`，**不會**從伺服器送出歡迎回覆；首次歡迎訊息須於 LINE 官方帳號後台（原生歡迎訊息）維護。`welcome_message.txt` 保留為核准的封存文案與選用 fallback。若明確設定 `WELCOME_DELIVERY=webhook`，才會在 FollowEvent 以 LINE reply API 回覆一則該檔案內容。

## 六格選單

| 位置 | 名稱 | 暫時行為 |
|---|---|---|
| 左上 | 認識藝術家 | 僅 `christy_p:about` 回覆 `about_artist.txt` |
| 上中 | 作品系列 | 靜默 postback，待作品資料 |
| 右上 | 周邊新品 | 靜默 postback，待發行品項與售價 |
| 左下 | 展覽與檔期 | 靜默 postback，待公開活動日期 |
| 下中 | 購買據點 | 靜默 postback，待藝廊／通路資訊 |
| 右下 | 合作洽詢 | 靜默 postback，待正式合作方式 |

部署時設定 `LINE_CHANNEL_SECRET` 和 `LINE_CHANNEL_ACCESS_TOKEN` 環境變數；服務不讀取或儲存憑證。`GET /health` 回 `OK`。預設 `GET /status` 回報 `native_welcome_and_about`、`welcome_delivery: line_official_account`、`greeting_enabled: true` 與 `about_artist_enabled: true`；若設定 webhook fallback，則回報 `webhook_welcome_and_about` 與 `welcome_delivery: webhook`。狀態端點僅表達服務設定意圖，**不是 LINE 官方帳號後台實際原生歡迎訊息已啟用或成功送達的證明**。

Webhook 的診斷日誌僅記錄事件類型與限定的錯誤狀態，絕不記錄 webhook payload、使用者 ID、reply token 或 access token。LINE 官方帳號的原生歡迎訊息及圖文選單由 LINE 管理；Flask 不會產生 rich menu 圖片。舊品牌程式與選單已另外封存並交付。若未來恢復其他回覆或排程，應依新品牌內容重新審核，**不要直接啟用舊版程式**。
